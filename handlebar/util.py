import re

def first(iterable):
    """A utility function that returns the first item in an iterable (if there is one), and returns None otherwise"""
    if iterable is None:
        return None
    else:
        try:
            return next(iter(iterable))
        except StopIteration:
            return None


class lazy_property:
    """From an excellent StackOverflow answer here: http://stackoverflow.com/a/6849299/1741965"""
    def __init__(self, parent_func):
        self.parent_func = parent_func
        self.func_name = parent_func.__name__

    def __get__(self, obj, cls):
        if obj is None:
            return None
        value = self.parent_func(obj)
        setattr(obj, self.func_name, value)  # Very elegant way to lazily initialize value
        return value

def to_title_case(name, articles=('a', 'an', 'of', 'the', 'is')):
    """Found in the StackOverflow answer here: http://stackoverflow.com/a/3729957/1741965"""
    word_list = re.split(' ', name)
    final = [word_list[0].capitalize()]
    for word in word_list[1:]:
        final.append(word in articles and word or word.capitalize())
    return " ".join(final)

def intersperse(iterable, delimiter):
    """Handy method to add a delimiter between every element of an 'iterable'.
    Found in this StackOverflow answer: http://stackoverflow.com/a/5656097/1741965"""
    it = iter(iterable)
    yield next(it)
    for x in it:
        yield delimiter
        yield x
