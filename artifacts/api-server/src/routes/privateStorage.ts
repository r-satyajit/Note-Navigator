import { Router, type IRouter, type Request, type Response } from "express";

import {
  getObjectAclPolicy,
  ObjectPermission,
  setObjectAclPolicy,
} from "../lib/objectAcl";
import {
  ObjectNotFoundError,
  ObjectStorageService,
} from "../lib/objectStorage";
import {
  requireStorageBridge,
  storageBridgeUserId,
} from "../middlewares/storageBridgeAuth";

const router: IRouter = Router();
const objectStorage = new ObjectStorageService();
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function parseObjectPath(value: unknown, userId: string): string | null {
  if (typeof value !== "string" || value.length > 512) {
    return null;
  }
  const parts = value.split("/");
  if (
    parts.length < 5 ||
    parts[0] !== "" ||
    parts[1] !== "objects" ||
    parts[2] !== userId ||
    parts.some((part, index) => index > 1 && (!part || part === "." || part === ".."))
  ) {
    return null;
  }
  return value;
}

async function getOwnedObject(
  req: Request,
  res: Response,
  objectPath: string,
): Promise<Awaited<ReturnType<ObjectStorageService["getObjectEntityFile"]>> | null> {
  const userId = storageBridgeUserId(req);
  try {
    const file = await objectStorage.getObjectEntityFile(objectPath);
    const policy = await getObjectAclPolicy(file);
    const canRead = await objectStorage.canAccessObjectEntity({
      userId,
      objectFile: file,
      requestedPermission: ObjectPermission.READ,
    });
    if (!policy || policy.owner !== userId || !canRead) {
      res.status(403).json({ error: "Forbidden" });
      return null;
    }
    return file;
  } catch (error) {
    if (error instanceof ObjectNotFoundError) {
      res.status(404).json({ error: "Object not found" });
      return null;
    }
    throw error;
  }
}

router.use(requireStorageBridge);

router.post(
  "/private-storage/uploads/request-url",
  async (req: Request, res: Response) => {
    const userId = storageBridgeUserId(req);
    const size = Number(req.body?.size);
    const contentType = req.body?.contentType;
    const spaceId = req.body?.spaceId;
    if (
      !Number.isInteger(size) ||
      size < 1 ||
      size > MAX_UPLOAD_BYTES ||
      typeof contentType !== "string" ||
      contentType.length > 160 ||
      typeof spaceId !== "string" ||
      !UUID_PATTERN.test(spaceId)
    ) {
      res.status(400).json({ error: "Invalid upload metadata" });
      return;
    }

    try {
      const result = await objectStorage.getUserUploadURL(userId, spaceId);
      res.json(result);
    } catch (error) {
      req.log.error({ err: error }, "Failed to create private upload URL");
      res.status(500).json({ error: "Failed to create upload URL" });
    }
  },
);

router.post(
  "/private-storage/uploads/abort",
  async (req: Request, res: Response) => {
    const userId = storageBridgeUserId(req);
    const objectPath = parseObjectPath(req.body?.objectPath, userId);
    if (!objectPath) {
      res.status(400).json({ error: "Invalid object path" });
      return;
    }

    try {
      const file = await objectStorage.getObjectEntityFile(objectPath);
      const policy = await getObjectAclPolicy(file);
      if (policy && policy.owner !== userId) {
        res.status(403).json({ error: "Forbidden" });
        return;
      }
      await file.delete();
      res.json({ success: true });
    } catch (error) {
      if (error instanceof ObjectNotFoundError) {
        res.json({ success: true });
        return;
      }
      req.log.error({ err: error }, "Failed to abort private upload");
      res.status(500).json({ error: "Failed to abort upload" });
    }
  },
);

router.post(
  "/private-storage/uploads/commit",
  async (req: Request, res: Response) => {
    const userId = storageBridgeUserId(req);
    const objectPath = parseObjectPath(req.body?.objectPath, userId);
    if (!objectPath) {
      res.status(400).json({ error: "Invalid object path" });
      return;
    }

    try {
      const file = await objectStorage.getObjectEntityFile(objectPath);
      const existingPolicy = await getObjectAclPolicy(file);
      if (existingPolicy && existingPolicy.owner !== userId) {
        res.status(403).json({ error: "Forbidden" });
        return;
      }
      await setObjectAclPolicy(file, { owner: userId, visibility: "private" });
      res.json({ success: true });
    } catch (error) {
      if (error instanceof ObjectNotFoundError) {
        res.status(404).json({ error: "Uploaded object not found" });
        return;
      }
      req.log.error({ err: error }, "Failed to apply private object policy");
      res.status(500).json({ error: "Failed to commit uploaded object" });
    }
  },
);

router.post(
  "/private-storage/download-url",
  async (req: Request, res: Response) => {
    const userId = storageBridgeUserId(req);
    const objectPath = parseObjectPath(req.body?.objectPath, userId);
    if (!objectPath) {
      res.status(400).json({ error: "Invalid object path" });
      return;
    }

    try {
      const file = await getOwnedObject(req, res, objectPath);
      if (!file) {
        return;
      }
      const downloadURL = await objectStorage.getObjectEntityDownloadURL(objectPath);
      res.json({ downloadURL });
    } catch (error) {
      req.log.error({ err: error }, "Failed to create private download URL");
      res.status(500).json({ error: "Failed to create download URL" });
    }
  },
);

router.post(
  "/private-storage/delete",
  async (req: Request, res: Response) => {
    const userId = storageBridgeUserId(req);
    const objectPath = parseObjectPath(req.body?.objectPath, userId);
    if (!objectPath) {
      res.status(400).json({ error: "Invalid object path" });
      return;
    }

    try {
      const file = await objectStorage.getObjectEntityFile(objectPath).catch((error) => {
        if (error instanceof ObjectNotFoundError) {
          return null;
        }
        throw error;
      });
      if (!file) {
        res.json({ success: true });
        return;
      }
      const policy = await getObjectAclPolicy(file);
      const canWrite = await objectStorage.canAccessObjectEntity({
        userId,
        objectFile: file,
        requestedPermission: ObjectPermission.WRITE,
      });
      if (!policy || policy.owner !== userId || !canWrite) {
        res.status(403).json({ error: "Forbidden" });
        return;
      }
      await file.delete();
      res.json({ success: true });
    } catch (error) {
      req.log.error({ err: error }, "Failed to delete private object");
      res.status(500).json({ error: "Failed to delete object" });
    }
  },
);

export default router;
