"""One scalable coordinate system for the approved graduated pearl necklace."""
import math


def geometry():
    samples = []
    mass = 0.0
    previous = None
    for i in range(6001):
        angle = math.radians(240 - 300 * i / 6000)
        x, y = 320 + 260 * math.cos(angle), 235 + 215 * math.sin(angle)
        diameter = 25 + 49 * ((math.sin(angle) + 1) / 2) ** 1.2
        if previous:
            mass += math.hypot(x - previous[0], y - previous[1]) / (diameter + 6)
        samples.append((mass, x, y, diameter))
        previous = (x, y)
    points = []
    cursor = 0
    for i in range(23):
        target = mass * i / 22
        while cursor < len(samples) - 1 and samples[cursor][0] < target:
            cursor += 1
        _, x, y, diameter = samples[cursor]
        points.append({'x': round(x, 4), 'y': round(y, 4), 'diameter': round(diameter, 4)})
    # Average mirrored samples to remove numerical integration drift.
    for i in range(len(points)//2):
        left, right = points[i], points[-i-1]
        x = (left['x'] + 640 - right['x']) / 2
        y = 235 + 215 * math.sqrt(max(0, 1 - ((x - 320)/260)**2)) * (1 if left['y'] > 235 else -1)
        diameter = (left['diameter'] + right['diameter'])/2
        left.update(x=round(x,4), y=round(y,4), diameter=round(diameter,4))
        right.update(x=round(640-x,4), y=round(y,4), diameter=round(diameter,4))
    points[11].update(x=320, y=450, diameter=74)
    return points


def markup(icon, badge):
    pearls = []
    for i, point in enumerate(geometry()):
        size = point['diameter'] * 1.24
        pearls.append(f'<image class="necklace-bead" data-bead="{i}" href="assets/pearl.webp" x="{point["x"]-size/2:.4f}" y="{point["y"]-size/2:.4f}" width="{size:.4f}" height="{size:.4f}"/>')
    art = '<svg class="necklace-art" viewBox="0 0 640 560" aria-hidden="true" focusable="false"><path class="necklace-cord" d="M 190 48.8045 A 260 215 0 1 0 450 48.8045"/>' + ''.join(pearls) + '</svg>'
    nodes = ''.join('<div><span class="icon-disc">' + icon(i) + '</span><br><small>' + title + '</small></div>' + ('<span aria-hidden="true">→</span>' if title != 'Result' else '') for i, title in [('search', 'Discover'), ('file', 'Review'), ('network', 'Connect'), ('file', 'Result')])
    return '<div class="necklace" aria-label="Individual agent capabilities connected into one useful outcome">' + art + '<div class="necklace-center">' + badge('Agent workflow') + '<h3>From individual agents to one useful result</h3><div class="row">' + nodes + '</div><a class="link-button" href="workflows.html">See how it works →</a></div><span class="necklace-label label-research">Research</span><span class="necklace-label label-news">News</span><span class="necklace-label label-documents">Documents</span></div>'
