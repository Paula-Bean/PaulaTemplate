#!/usr/bin/env python2
# encoding: utf8

# TODO: { } to « »  (MacOS: Alt-\ and Shift-Alt-\)
# TODO: 100% coverage
# TODO: spotless unittests
# TODO: convert to Python3
# TODO: be able to access members in template vars: {=person.lastname}
# TODO: with tokens and Lits and Conds etc, store the line/charpos of the position in the template for better error messages
# TODO: String-only mode
# TODO: In Python3, test performance again with A) StringIO, B) concat fest, C) lines.append() method

import os
import pprint
import re
import unittest
import codecs
import functools

CHOPNAME = 1
CHOPITEM = 2

whitechars = re.compile("\s")
rangerep = re.compile("(\w+)\:(-?[0-9|x]+):(-?[0-9|x]+)")

verbose = False
exceptionless = True  # False: throw exceptions when something is wrong with the template or rendering it; True: insert an error in the output text instead.


def indent(level):
    return "| " + "    " * level


class Container(list):
    "Generic container."

    def __init__(self, name=""):
        self.name = name

    def __repr__(self):
        tag = "%s %s" % (self.__class__.__name__, self.name)
        return "%s: %s" % (tag.strip(), super(Container, self).__repr__())

    def render(self, vars, last=False, level=0):
        if verbose:
            print("%sContainer.render(vars=%s,last=%s) type(vars)=%s, self.name=%s" % (indent(level), vars, last, type(vars), self.name))
        output = ""
        for child in self:
            if verbose:
                print("%sContainer.render child %s" % (indent(level), child))
            value = child.render(vars, last, level + 1)
            if value:
                try:
                    output += value
                except UnicodeDecodeError as e:
                    msg = "Container.render() child %s raises %s, value: %s, %r" % (child.__class__.__name__, e, type(value), value)
                    raise Exception(msg)
        return output


class Lit(Container):
    "Container for literal content."

    def __init__(self, contents=""):
        super(Lit, self).__init__()
        self.append(contents)

    def __repr__(self):
        return super(Lit, self).__repr__()

    def render(self, vars, last=None, level=0):
        if verbose:
            print("%sLit.render(vars=%s,last=%s) type(vars)=%s, self=%s" % (indent(level), vars, last, type(vars), self))
        return self[0]




class Sep(Container):
    "Container for separator. Same as Lit, but doesn't result in output in the last iteration of a Rep."

    def __init__(self, name):
        super(Sep, self).__init__(name)

    def __repr__(self):
        return super(Sep, self).__repr__()

    def render(self, vars, last, level):
        if verbose:
            print("%sSep.render(vars=%s) type(vars)=%s, self=%s" % (indent(level), vars, type(vars), self))
        if last:
            if verbose:
                print("%sSep.render last is True, empty string returned" % indent(level))
            return ""
        output = ""
        for child in self:
            if verbose:
                print("%sSep.render child %s" % (indent(level), child))
            value = child.render(vars, last, level + 1)
            if value:
                output += value
        return output


class Sub(Container):
    "Container for a variable substitution."

    def __init__(self, name):
        super(Sub, self).__init__(name)

    def __repr__(self):
        return super(Sub, self).__repr__()

    def render(self, vars, last, level):
        if verbose:
            print("%sSub.render(vars=%s) type(vars)=%s, self.name=%s" % (indent(level), vars, type(vars), self.name))
        try:
            value = vars[self.name]
        except TypeError:
            value = getattr(vars, self.name)
        except KeyError:
            return '<span class="paulatemplate_error" style="background-color: red; color: white;">Template error in Sub: unknown variable "%s"</span>' % self.name
        if isinstance(value, (int, float)):
            value = str(value)
        return value


class Cond(Container):
    "Container for conditional content."

    def __init__(self, name, inverting=False):
        super(Cond, self).__init__(name)
        self.inverting = inverting

    def __repr__(self):
        return super(Cond, self).__repr__()

    def render(self, vars, last, level):
        if verbose:
            print("%sCond.render(vars=%s) type(vars)=%s, self.name=%s, self.inverting=%s" % (indent(level), vars, type(vars), self.name, self.inverting))
        ok = vars.get(self.name)  # Assume missing template variable is False.
        if self.inverting:
            ok = not ok
        if not ok:
            if verbose:
                print("%sCond.render cond is False, empty string returned" % indent(level))
            return ""
        output = ""
        for child in self:
            if verbose:
                print("%sCond.render child %s" % (indent(level), child))
            value = child.render(vars, last, level + 1)
            if value:
                output += value
        return output


class Rep(Container):
    "Container for repeating content."

    def __init__(self, name):
        super(Rep, self).__init__(name)

    def __repr__(self):
        return super(Rep, self).__repr__()


    def render(self, vars, last, level):
        if verbose:
            print("%sRep.render(vars=%s) type(vars)=%s, self.name=%s" % (indent(level),vars,type(vars),self.name))
        output = ""
        #if not self.name in vars:
        #    raise NameNotFound("A required variable name '%s' was not present in '%r'" % (self.name, vars))
        # TODO: This can provide useful debugging info: if not self.name in vars: raise NameNotFound("A required variable name '%s' was not present in '%r'" % (self.name, vars))
        try:
            subvars = vars[self.name]  # A KeyError here means that a required variable wasn't present.
        except TypeError:
            subvars = getattr(vars, self.name)
        except KeyError:
            return '<span class="paulatemplate_error" style="background-color: red; color: white;">Template error in Rep: unknown variable "%s"</span>' % self.name
        for nr, subvar in enumerate(subvars):
            if verbose:
                print("%sRep.render subvar=%s, type(subvar)=%s" % (indent(level),subvar,type(subvar)))
            for child in self:
                last = nr == len(subvars)-1
                if verbose:
                    print("%sRep.render child %s, last=%s" % (indent(level), child,last))
                output += child.render(subvar, last, level+1)
        return output


def splitfirst(s):
    "Split a string into a first special word, and the rest."
    if not s:
        return "", ""
    if s[0] in createinfo:
        parts = whitechars.split(s, 1)
        if len(parts) < 2:
            return s, ""
        else:
            return tuple(parts)
    else:
        return "", s


def feed(seq):
    for item in seq:
        yield item


def lexer(it):
    """Split input into tokens. A token is either an open curly brace, a closing curly brace, or a string without curly braces."""
    tokens = []
    token = ""
    for c in it:
        if c == "{":
            if token:
                tokens.append(token)
                token = ""
            tokens.append(c)
        elif c == "}":
            if token:
                tokens.append(token)
                token = ""
            tokens.append(c)
        else:
            token += c
    if token:
        tokens.append(token)
    return tokens


def parse(it, node, nesting=0):
    """Build a (recursive) nested list from the tokens."""
    for token in it:
        if token == "{":
            subnode = []
            node.append(subnode)
            parse(it, subnode, nesting + 1)
        elif token == "}":
            if nesting == 0:
                raise Exception("Unbalanced }")
            return
        else:
            node.append(token)


createinfo = {
    "?": (Cond, CHOPNAME),
    "!": (functools.partial(Cond, inverting=True), CHOPNAME),
    "#": (Rep, CHOPNAME),
    "=": (Sub, CHOPITEM),
    "/": (Sep, CHOPNAME),
    }


def compile(node, into, level=0):
    if verbose:
        print("%s compile: " % indent(level), node)
    for pos, item in enumerate(node):
        if isinstance(item, list):
            if verbose:
                print("%s #%d list: %r" % (indent(level), pos, item))
            head = item[0]
            if not head[0] in createinfo:
                if exceptionless:
                    return Lit("<span style=\"background-color: red; color: white;\">Template error: '{' without a following valid metachar</span>")
                else:
                    raise ValueError("'{' without a following valid metachar")
            first, rest = splitfirst(head)
            operator, name = first[0], first[1:]
            if verbose:
                print("%s operator %s, name %s, rest %r" % (indent(level), operator, name, rest))
            # Create correct container
            factoryfunc, options = createinfo[operator]
            ob = factoryfunc(name)
            if options == CHOPNAME:
                item[0] = rest
            elif options == CHOPITEM:
                item = item[1:]
            into.append(compile(item, ob, level + 1))
        else:
            if verbose:
                print("%s #%d item: %s" % (indent(level), pos, item))
            into.append(Lit(item))
    return into


def process(sourcetext):
    if verbose:
        print("\n\n\nCompile phase")
    tokens = lexer(feed(sourcetext))
    # root = Container()
    root = []
    parse(feed(tokens), root)
    result = compile(root, Container())
    if verbose:
        print("Compile result:", result)
    return result


class Paulatemplate(object):
    """Simple templating class."""

    def __init__(self, s=None, name=None):
        """Initialize a template, optionally from a template string."""
        if s:
            self.root = process(s)
        elif s is not None:
            self.root = Container()
            self.root.append(Lit(""))
        else:
            self.root = None
        self.name = name

    def fromfile(self, fn):
        """Load a template from a file.
        Allows: tem = Paulatemplate().fromfile("hello.tpl")
        The template file should contain UTF-8 encoded unicode text
        """
        self.root = process(codecs.open(fn, "r", "utf8").read())
        self.name = fn.replace(" ", "_")
        return self

    def pprint(self):
        """Pretty-print the template structure."""
        pprint.pprint(self.root)

    def render(self, vars):
        """Renders the template to a string, using the supplied variables."""
        if verbose:
            print("\nRender phase")
        if not self.root:
            raise Exception("You should either pass a template as a string in the constructor, or use 'fromfile' to read the template from file")
        result = self.root.render(vars)
        if verbose:
            print("Render result:", result)
        return result


class Test(unittest.TestCase):
    """Unittest for Paulatemplate."""

    def test_naming(self):
        """Test the naming; every template instance can have a name (usually the filename where it was loaded from).
        This name is used in error reporting."""
        tems = "{=name}"
        tem = Paulatemplate(tems, "nametest")
        self.assertEqual(tem.name, "nametest")

    def test_badmetachar(self):
        tems = "{&name}"  # Note that '&' is illegal after a '{'.
        #
        global exceptionless
        prevexceptionless = exceptionless
        #
        exceptionless = False
        self.assertRaises(ValueError, Paulatemplate, tems)
        #
        exceptionless = True
        tem = Paulatemplate(tems)
        res = tem.render({})
        self.assertTrue("Template error" in res)
        exceptionless = prevexceptionless

    def test_splitting(self):
        self.assertEqual(splitfirst(""), ("", ""))
        self.assertEqual(splitfirst("?hi"), ("?hi", ""))
        self.assertEqual(splitfirst("?hi there"), ("?hi", "there"))
        self.assertEqual(splitfirst("hi"), ("", "hi"))
        self.assertEqual(splitfirst("hi there"), ("", "hi there"))

    def test_render(self):
        """Test a number of progressively complex render cases. (template source code, context variables, expected result text)."""
        goodcases = (
            # Empty template.
            ("", {}, ""),
            # Just a letter.
            ("a", {}, "a"),
            # Longer string.
            ("hi there", {}, "hi there"),
            # Simple substitution.
            ("{=status}", {"status": "STATUS"}, "STATUS"),
            ("{=status}", {"status": 67.2334}, "67.2334"),
            ("{=status}", {"status": None}, ""),
            ("{=status}", {"status": False}, "False"),
            ("BEFORE{=status}", {"status": "STATUS"}, "BEFORESTATUS"),
            ("{=status}AFTER", {"status": "STATUS"}, "STATUSAFTER"),
            # Two substitutions in different flavors.
            ("{=one}{=two}", {"one": "ONE", "two": "TWO"}, "ONETWO"),
            ("{=one}AND{=two}", {"one": "ONE", "two": "TWO"}, "ONEANDTWO"),
            ("{=one} {=two}", {"one": "ONE", "two": "TWO"}, "ONE TWO"),
            ("{=one}   {=two}", {"one": "ONE", "two": "TWO"}, "ONE   TWO"),
            ("{=one}, {=two}", {"one": "ONE", "two": "TWO"}, "ONE, TWO"),
            ("{=one} ({=two})", {"one": "ONE", "two": "TWO"}, "ONE (TWO)"),
            # Substitution with text in between.
            ("well{=here}it{=goes}with{=some}test",
                {"here": "HERE", "goes": "GOES", "some": "SOME"},
                "wellHEREitGOESwithSOMEtest"),

            ('{?useimg hallo <img src="path/names/{=component}/with/{=component}.jpg">}',
                {"useimg": True, "component": "filesystem"},
                'hallo <img src="path/names/filesystem/with/filesystem.jpg">'),

            # Simple repetitions.
            ("{#cls{=co}}",
                {"cls": ({"co": "red"}, {"co": "gr"}, {"co": "bl"})},
                "redgrbl"),
            ("{#cls <{=co}>}",
                {"cls": ({"co": "red"}, {"co": "gr"}, {"co": "bl"})},
                "<red><gr><bl>"),
            ("{#cls {=co}, }",
                {"cls": ({"co": "red"}, {"co": "gr"}, {"co": "bl"})},
                "red, gr, bl, "),
            ("{#cls {=co} x }",
                {"cls": ({"co": "red"}, {"co": "gr"}, {"co": "bl"})},
                "red x gr x bl x "),
            ("{#cls {=co} _}",
                {"cls": ({"co": "red"}, {"co": "gr"}, {"co": "bl"})},
                "red _gr _bl _"),
            # Simple conditions.
            ("throw a {?condition big }party",
                {"condition": True},
                "throw a big party"),
            ("throw a {?condition big }tantrum",
                {"condition": 42},
                "throw a big tantrum"),
            ("throw a {?condition big }party",
                {"condition": False},
                "throw a party"),
            ("throw a {?condition big }tantrum",
                {"condition": None},
                "throw a tantrum"),
            ("A!{?condition B}!C!{!condition D}!E",
                {"condition": True},
                "A!B!C!!E"),
            ("A!{?condition B}!C!{!condition D}!E",
                {"condition": False},
                "A!!C!D!E"),
            # Repeats.
            ("{#a{=b}{=c}}",
                {"a": ({"b": 11, "c": 22},)},
                "1122"),
            ("{#a {=b} {=c}}",
                {"a": [{"b": 33, "c": 44}]},
                "33 44"),
            ("{#a STA{=b}STO  BEG{=c}END }",
                {"a": ({"b": 55, "c": 66},)},
                "STA55STO  BEG66END "),
            ("{#a {=b} {=c}}",
                {"a": ({"b": 7.70, "c": 88}, {"b": 99, "c": 1.234567})},
                "7.7 8899 1.234567"),
            ("{#a {=b} {=c}}", {"a": ()}, ""),
            # Repeat with variabele as last on the line.
            ("{#blop\n{=you}}",
                dict(blop=(dict(you=123), dict(you=456))),
                "123456"),
            ("{#blop\n{=you}\n}",
                dict(blop=(dict(you=123), dict(you=456))),
                "123\n456\n"),
            # A join()-like separator.
            ("{#colors {=color}{/comma , }}",
                dict(colors=(dict(color="red"), dict(color="green"),
                     dict(color="blue"))),
                "red, green, blue"),
            # More repeats.
            ("buy {=count} articles: {#articles {=nam} txt {=pri}, }", {
                "count": 2,
                "articles": ({"nam": "Ur", "pri": 1}, {"nam": "Mo", "pri": 2})
                },
                "buy 2 articles: Ur txt 1, Mo txt 2, "),

            ("sell {=count} stocks: {#articles {=nam} &euro; {=pri}{/comma , }}",
                {"count": 2, "articles": ({"nam": "APPL", "pri": 320}, {"nam": "GOOG", "pri": 120})},
                "sell 2 stocks: APPL &euro; 320, GOOG &euro; 120"),
            # Nested repeats.
            ("Contents: {#chapters Chapter {=name}. {#sections Section {=name}. }",
                {
                    "chapters": [
                        dict(name="Intro", sections=[dict(name="Foreword"), dict(name="Methodology")]),
                        dict(name="Middle", sections=[dict(name="Measuring"), dict(name="Calculation"), dict(name="Results")]),
                        dict(name="Epilogue", sections=[dict(name="Conclusion")])
                        ]
                    },
                "Contents: Chapter Intro. Section Foreword. Section Methodology. "
                "Chapter Middle. Section Measuring. Section Calculation. Section Results. "
                "Chapter Epilogue. Section Conclusion. "),
            # Condition with repeat.
            ("Dear {=name}, {?market Please get the following groceries:\n"
                "{#groceries \tItem: {=item}, {=count} pieces\n}}"
                "{?deadline Please be back before {=time}!}",
                {"name": "Joe",
                 "market": "True",
                 "count": 5,
                 "groceries": [dict(item="lemon", count=2), dict(item="cookies", count=4)],
                 "deadline": True,
                 "time": "17:30",
                 },
                "Dear Joe, Please get the following groceries:\n\tItem: "
                "lemon, 2 pieces\n\tItem: cookies, 4 pieces\nPlease be "
                "back before 17:30!"),
            )

        for tems, temv, expected in goodcases:
            tem = Paulatemplate(tems)  # tem.pprint()
            self.assertEqual(tem.render(temv), expected)

        ''' TODO: This still needs some work - sensible error reporting.
        badcases = (
            ("{#a {=b} {=c}}", {}), # required variables missing
            ("=a}", dict(a=42)), # missing opening {
            # ("{=a", dict(a=42)), # missing closing {
            )

        global exceptionless
        exceptionless = False
        for tems, temv in badcases:
            self.assertRaises(Exception, Paulatemplate(tems).render(temv))
        '''

    def test_namedtuple(self):
        import collections
        Entry = collections.namedtuple("Entry", ["name", "telephone"])
        phonebook = [Entry("Mary", "0203898"), Entry("Jan", "0683928")]
        tem = Paulatemplate("{#phonebook {=name} {=telephone}{/sep , }}")
        self.assertEqual(tem.render(dict(phonebook=phonebook)), "Mary 0203898, Jan 0683928")


def test_performance():
    """Paulatemplate and Jinja2 go head-to-head!
    Result for nr=150 on my MacBook Air:
        Paulatemplate: 467MB produced in 66.237 sec
        Jinja2: 470MB produced in 156.205 sec
    """
    import time
    nr = 2
    books = []
    d = {"books": books}
    for booknr in range(nr):
        chapters = []
        book = dict(title="%d bottles of beer" % booknr, toc="This will be the table of contents.", chapters=chapters)
        books.append(book)
        for chapternr in range(nr):
            sections = []
            chapter = dict(title="%d. How to drink beer" % chapternr, intro="This will be an intro", sections=sections)
            chapters.append(chapter)
            for sectionnr in range(nr):
                section = dict(title="%d. Procedure" % sectionnr, text="This will be an explanation of how to drink beer.")
                sections.append(section)
    tem = Paulatemplate("""
        {#books
            <h1>The Book Of {=title}</h1>
            <p>{=toc}</p>
            {#chapters
                <h2>Chapter {=title}</h2>
                <p>{=intro}</p>
                {#sections
                    <h3>Section {=title}</h3>
                    <p>{=text}</p>
                }
            }
        }
        """)
    start = time.time()
    res = tem.render(d)
    dur = time.time() - start
    print("paulatemplate: %dMB produced in %.3f sec:" % (len(res) / 1024 / 1024, dur))
    if nr < 3:
        print(res)
    #
    from jinja2 import Template
    tem = Template("""
        {% for book in books %}
            <h1>The Book Of {{book.title}}</h2>
            <p>{{book.toc}}</p>
            {% for chapter in book.chapters %}
                <h2>Chapter {{chapter.title}}</h2>
                <p>{{chapter.intro}}</p>
                {% for section in chapter.sections %}
                    <h3>Section {{section.title}}</h3>
                    <p>{{section.text}}</p>
                {% endfor %}
            {% endfor %}
        {% endfor %}
        """)
    start = time.time()
    res = tem.render(dict(books=books))
    dur = time.time() - start
    print("jinja2: %dMB produced in %.3f sec:" % (len(res) / 1024 / 1024, dur))
    if nr < 3:
        print(res)


if __name__ == "__main__":
    # For the usual unittests:
    unittest.main()

    # Uncomment for a benchmark comparison:
    # test_performance()
