import re, html, sys
data = sys.stdin.read()
# html.unescape already handles named and numeric entities.
sys.stdout.write(html.unescape(data))
