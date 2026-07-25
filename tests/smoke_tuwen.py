"""Smoke test for the tuwen (image post) feature."""
import sys
sys.path.insert(0, '.')

import dydownload.pipeline as p
import dydownload.video_parser as vp
import dydownload.downloader as dl
import dydownload.cli as cli
import dydownload.server as srv
import dydownload.gui as gui

# VideoInfo defaults
v = vp.VideoInfo(video_id='1', desc='', author_nickname='', author_unique_id='',
                 create_time=0, duration_ms=0, width=0, height=0, no_watermark_url='')
assert v.media_type == 'video', v.media_type
assert v.is_image is False

# VideoInfo image mode
v2 = vp.VideoInfo(video_id='2', desc='', author_nickname='', author_unique_id='',
                  create_time=0, duration_ms=0, width=0, height=0,
                  no_watermark_url='', media_type='image', images=['a','b'])
assert v2.is_image is True
assert len(v2.images) == 2

# URL extraction
assert p.extract_aweme_id('https://www.douyin.com/note/7123456789012345678/') == '7123456789012345678'
assert p.extract_aweme_id('https://www.douyin.com/video/7123456789012345678/') == '7123456789012345678'
assert p.extract_aweme_id('https://www.iesdouyin.com/share/video/7123456789012345678/') == '7123456789012345678'
assert p.extract_aweme_id('7123456789012345678') == '7123456789012345678'
assert p.extract_aweme_id('https://example.com') == ''

# extract_url handles note + share text
assert 'note/' in p.extract_url('https://www.douyin.com/note/7123456789012345678/')
assert p.extract_url('5.66 PXM:/ x https://v.douyin.com/abc/ 复制此链接').startswith('https://v.douyin.com/')

# sanitize_basename
assert '/' not in p.sanitize_basename('hello/world:a*b')
assert '|' not in p.sanitize_basename('a|b')

# _ext_from_url
assert p._ext_from_url('https://x.com/foo.jpg?x=1', 'mp4') == 'jpg'
assert p._ext_from_url('https://x.com/foo.JPEG', 'mp4') == 'jpg'
assert p._ext_from_url('https://x.com/foo.webp', 'mp4') == 'webp'
assert p._ext_from_url('https://x.com/foo.mp4', 'jpg') == 'mp4'
assert p._ext_from_url('https://x.com/foo', 'mp4') == 'mp4'

# _pick_image_url prefers jpeg (lives in video_parser)
urls = ['https://cdn/x.webp', 'https://cdn/x.jpeg?a=1', 'https://cdn/x.png']
assert 'jpeg' in vp._pick_image_url(urls)

# _pick_image_url avoids heic if possible
urls2 = ['https://cdn/x.heic', 'https://cdn/x.png']
assert 'png' in vp._pick_image_url(urls2)

# Module surface checks
assert callable(p.download_aweme)
assert callable(p.resolve_aweme)
assert p.DownloadResult is not None
assert p.VideoResult is not None
assert p.ImageResult is not None

# CLI app has expected commands (typer derives name from callback if .name is None)
cmd_names = {
    (c.name or (c.callback.__name__ if c.callback else None))
    for c in cli.app.registered_commands
}
assert {'download', 'test', 'status', 'serve'} <= cmd_names, cmd_names

# downloader has both functions
assert callable(dl.download_video)
assert callable(dl.download_image)

# Server download endpoint exists
assert hasattr(srv.CookieReceiverHandler, '_handle_download')

print('ALL OK')