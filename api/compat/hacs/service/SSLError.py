import ssl

import httpx


def get_legacy_session():
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
    return httpx.AsyncClient(verify=ctx, follow_redirects=True)
