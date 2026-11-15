"""/privacy and /terms point at the published policy pages (E12, PM 11-15).

Short, stable addresses for directory listings and footers. The texts live once, in new/en/privacy.html and
new/en/terms.html (the full policy pages, served since 11-10); a 301 keeps one source. 26494f3f had rendered the
shorter footer-dialog texts here instead, a second version of the policies (fixed the same day).
"""
PAGES = {'/privacy': '/new/en/privacy.html', '/terms': '/new/en/terms.html'}


def legal_router():
    from fastapi import APIRouter
    from fastapi.responses import RedirectResponse
    router = APIRouter()

    def endpoint(target):
        def serve():
            return RedirectResponse(target, status_code=301, headers={'Cache-Control': 'public, max-age=86400'})
        return serve

    for path, target in PAGES.items():
        router.add_api_route(path, endpoint(target), methods=['GET', 'HEAD'], include_in_schema=False)
    return router
