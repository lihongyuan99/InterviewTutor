import { toast } from "sonner";

/** 统一的 toast 反馈入口，替代散落的 alert/console.error */

export function notifyError(message: string) {
  toast.error(message);
}

export function notifySuccess(message: string) {
  toast.success(message);
}

export function notifyInfo(message: string) {
  toast.info(message);
}
