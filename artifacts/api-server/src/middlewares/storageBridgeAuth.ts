import {
  createHash,
  createHmac,
  timingSafeEqual,
} from "node:crypto";
import type { NextFunction, Request, Response } from "express";

type BridgeRequest = Request & {
  bridgeUserId?: string;
  rawBody?: Buffer;
};

const seenNonces = new Map<string, number>();
const MAX_CLOCK_SKEW_MS = 60_000;
const NONCE_TTL_MS = 5 * 60_000;

export function requireStorageBridge(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  const secret = process.env.SESSION_SECRET;
  const userId = req.header("x-nn-user-id") || "";
  const timestamp = req.header("x-nn-timestamp") || "";
  const nonce = req.header("x-nn-nonce") || "";
  const signature = req.header("x-nn-signature") || "";
  const rawBody = (req as BridgeRequest).rawBody ?? Buffer.alloc(0);

  if (!secret) {
    req.log.error("SESSION_SECRET is required for private storage requests");
    res.status(503).json({ error: "Private storage is not configured" });
    return;
  }
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      userId,
    ) ||
    !/^\d{10,13}$/.test(timestamp) ||
    !/^[A-Za-z0-9_-]{20,100}$/.test(nonce) ||
    !/^[0-9a-f]{64}$/i.test(signature)
  ) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  const requestTime = Number(timestamp);
  const timestampMs = timestamp.length === 13 ? requestTime : requestTime * 1000;
  if (!Number.isFinite(timestampMs) || Math.abs(Date.now() - timestampMs) > MAX_CLOCK_SKEW_MS) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  const requestPath = req.originalUrl.split("?")[0];
  const bodyHash = createHash("sha256").update(rawBody).digest("hex");
  const signedMessage = [
    userId,
    timestamp,
    nonce,
    req.method.toUpperCase(),
    requestPath,
    bodyHash,
  ].join("\n");
  const expected = createHmac("sha256", secret).update(signedMessage).digest();
  const supplied = Buffer.from(signature, "hex");
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  const nonceKey = `${userId}:${nonce}`;
  const currentTime = Date.now();
  if (seenNonces.has(nonceKey)) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }
  seenNonces.set(nonceKey, currentTime + NONCE_TTL_MS);
  if (seenNonces.size > 1000) {
    for (const [key, expiresAt] of seenNonces) {
      if (expiresAt <= currentTime) {
        seenNonces.delete(key);
      }
    }
  }

  (req as BridgeRequest).bridgeUserId = userId;
  next();
}

export function storageBridgeUserId(req: Request): string {
  const userId = (req as BridgeRequest).bridgeUserId;
  if (!userId) {
    throw new Error("Storage bridge authentication was not applied.");
  }
  return userId;
}
