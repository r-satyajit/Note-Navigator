import { Router, type IRouter } from "express";
import healthRouter from "./health";
import privateStorageRouter from "./privateStorage";

const router: IRouter = Router();

router.use(healthRouter);
router.use(privateStorageRouter);

export default router;
