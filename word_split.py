import re

# 粘连词拆分：在小写转大写、以及全大写缩写结尾处插一个空格。
# 两条正则取自 inflection 的 underscore()，只把第二条里的 \d 去掉——
# 数字不算边界，AK74 / M4A1 / MP5K / Battery9V 这类名字才不会被拆散。
_ACRONYM_TAIL = re.compile(r"([A-Z]+)([A-Z][a-z])")
_LOWER_TO_UPPER = re.compile(r"([a-z])([A-Z])")


def split_stuck_words(text):
    """把连成一片的英文拆开：AsaraShotGun -> Asara Shot Gun。

    本来就带空白的文本（正常句子）原样返回，一个字不动。
    """
    if not text or any(char.isspace() for char in text):
        return text
    text = _ACRONYM_TAIL.sub(r"\1 \2", text)
    return _LOWER_TO_UPPER.sub(r"\1 \2", text)
