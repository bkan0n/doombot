from extensions.fun import _COMMON_WORDS, _EMOJI_MAP, emojify, uwuify


def test_uwuify_replaces_l_and_r_preserving_case():
    assert uwuify("Hello world, LORD!") == "Hewwo wowwd, WOWD!"


def test_uwuify_leaves_other_characters_untouched():
    assert uwuify("guns 123") == "guns 123"


def test_emojify_skips_common_words():
    assert emojify("the of and") == "the of and"


def test_emojify_passes_unknown_words_through():
    assert emojify("qzxqzx") == "qzxqzx"


def test_emojify_appends_a_mapped_emoji_after_the_word():
    word = next(w for w in _EMOJI_MAP if w not in _COMMON_WORDS and w.isalpha())
    out = emojify(word).split()
    assert out[0] == word
    assert len(out) == 2
    assert out[1] in _EMOJI_MAP[word]
