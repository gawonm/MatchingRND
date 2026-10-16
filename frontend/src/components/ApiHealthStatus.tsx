import { useCallback, useEffect, useState } from 'react';
import { Badge, Button } from 'react-bootstrap';
import { getHealth } from '../api';

type HealthState = 'loading' | 'ok' | 'error';

export default function ApiHealthStatus() {
  const [state, setState] = useState<HealthState>('loading');

  const check = useCallback(() => {
    void getHealth().then(() => setState('ok')).catch(() => setState('error'));
  }, []);

  useEffect(check, [check]);

  if (state === 'loading') return <Badge bg="secondary" aria-live="polite">API 연결 확인 중</Badge>;
  if (state === 'ok') return <Badge bg="success" aria-live="polite">API 연결됨</Badge>;
  return <Button size="sm" variant="outline-danger" onClick={() => { setState('loading'); check(); }} aria-live="polite">API 연결 실패 · 재시도</Button>;
}
