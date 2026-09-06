import { createPortal } from 'react-dom';

export function Notification({ message, kind = 'notice', onClose }: {
  message: string; kind?: 'error' | 'notice' | 'working'; onClose?: () => void;
}) {
  if (!message) return null;
  return createPortal(<div className={`notification ${kind}`} role={kind === 'error' ? 'alert' : 'status'} aria-atomic="true">
    <div className="notification-content"><strong>{kind === 'error' ? '오류' : kind === 'working' ? '처리 중' : '알림'}</strong><p>{message}</p></div>
    {onClose && <button type="button" className="notification-close" aria-label="알림 닫기" onClick={onClose}>×</button>}
  </div>, document.getElementById('notifications')!);
}
