"""Serve a generated package under a separate browser origin without a project server."""
from zipfile import ZipFile


def open_hosted_package(page, path, root='https://customer.example/apps/workflow/'):
    with ZipFile(path) as package:
        files = {name: package.read(name) for name in package.namelist()}
    def hosted(route):
        relative = route.request.url.removeprefix(root) or 'index.html'
        body = files.get(relative)
        if body is None:
            return route.fulfill(status=404, body='Not found')
        kind = 'application/javascript' if relative.endswith('.js') else 'text/css' if relative.endswith('.css') else 'text/html'
        route.fulfill(status=200, body=body, content_type=kind)
    page.context.route(root + '**', hosted)
    page.goto(root)
    return files
