export type GeminiExecutionState = {
  credential_slot?: 'primary' | 'backup' | null; fallback_reason?: string | null;
  fallback_status?: 'backup_unavailable' | 'attempt_limit' | 'call_limit' | 'backup_retry_wait' | null;
  credential_selected_at?: string | null; source_credential_slot?: 'primary' | 'backup' | null;
  source_fallback_reason?: string | null;
};

const reasons: Record<string, string> = {
  primary_unregistered: '주키 미등록', primary_removed: '주키 제거', primary_file_unavailable: '주키 파일 미가용',
  primary_decrypt_failed: '주키 복호화 실패', primary_restore_required: '복원 후 주키 재등록 필요',
  primary_authentication: '주키 인증 실패', primary_payment_required: '주키 결제 조건 확인 필요',
  primary_permission_denied: '주키 권한 실패', primary_api_key_invalid: '주키 인증 오류',
  primary_rate_limit: '주키 요청 제한', primary_service_unavailable: '주키 공급자 일시 장애', primary_connection_lost: '주키 연결 유실',
};
const statuses = { backup_unavailable: '예비키 미가용 · 개발자 설정 필요', attempt_limit: '시도 상한 도달 · 추가 전환 불가', call_limit: '호출 상한 도달 · 추가 전환 불가', backup_retry_wait: '예비키 전환 재시도 대기' };

export function GeminiExecution({ value, reused = false }: { value: GeminiExecutionState; reused?: boolean }) {
  const slot = reused ? value.source_credential_slot : value.credential_slot;
  const reason = reused ? value.source_fallback_reason : value.fallback_reason;
  const selected = !!value.credential_selected_at;
  return <p className="fine">{reused ? '재사용 출처 · ' : ''}{!reused && slot === 'backup' && value.fallback_status === 'backup_retry_wait' ? '예비키 전환 대기' : slot ? `${slot === 'primary' ? '주키' : '예비키'} ${reused ? '사용 기록' : selected ? '사용' : '선택 미완료'}` : '키 역할 기록 없음'}
    {reason && reasons[reason] && ` · ${reasons[reason]}${slot === 'backup' && (reused || selected) ? ' 후 전환' : ''}`}
    {!reused && value.fallback_status && ` · ${statuses[value.fallback_status]}`}
    {!reused && value.credential_selected_at && ` · ${new Date(value.credential_selected_at).toLocaleString()}`}
  </p>;
}
