import os
from typing import Optional

from fastapi import Header, HTTPException, Query


def require_deep_token(x_sa_token: Optional[str] = Header(None), token: Optional[str] = Query(None)) -> None:
    """Gates /deep/* and /review/resolve. A deep run takes several minutes and
    the API has allow_origins=["*"] on a public IP — this is a shared-secret
    speed bump against opportunistic/bot hits, not a defense against a
    determined attacker (the token, once known to the browser, is visible in
    devtools like any client-side value). Fails closed if unconfigured
    rather than silently running unprotected in production.

    EventSource can't set custom headers, so /deep/stream accepts the token
    as a query param too.
    """
    expected = os.getenv("SA_DEEP_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="SA_DEEP_TOKEN 未配置，深度分析接口已禁用")
    if (x_sa_token or token) != expected:
        raise HTTPException(status_code=403, detail="口令错误或缺失")
