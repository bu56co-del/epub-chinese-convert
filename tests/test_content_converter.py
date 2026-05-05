from epubconv.converters.content import convert_xhtml
from epubconv.engines.opencc_engine import OpenCCEngine


def _engine():
    return OpenCCEngine("zh-CN", "zh-TW", config="s2t")


def test_paragraph_text_converted():
    src = (
        '<?xml version="1.0"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>简体中文</p>'
        '</body></html>'
    )
    out = convert_xhtml(src, _engine())
    assert "簡體中文" in out
    assert "简体中文" not in out


def test_code_and_pre_preserved():
    src = (
        '<?xml version="1.0"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p>简体</p>'
        '<code>简体</code>'
        '<pre>简体代码</pre>'
        '</body></html>'
    )
    out = convert_xhtml(src, _engine())
    assert "<p>簡體</p>" in out
    assert "<code>简体</code>" in out
    assert "<pre>简体代码</pre>" in out


def test_alt_and_title_converted():
    src = (
        '<?xml version="1.0"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<img src="cover.jpg" alt="封面" title="书的封面"/>'
        '</body></html>'
    )
    out = convert_xhtml(src, _engine())
    assert 'alt="封面"' in out
    assert '書的封面' in out


def test_nested_tags_walked():
    src = (
        '<?xml version="1.0"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<div><p><strong>简体</strong>中文</p></div>'
        '</body></html>'
    )
    out = convert_xhtml(src, _engine())
    assert "簡體" in out
    assert "中文" in out
