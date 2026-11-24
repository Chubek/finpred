from pygments.lexer import RegexLexer
from pygments.token import Text, Keyword, Name, Number, Operator, Error
from pygments import highlight
from pygments.formatters import HtmlFormatter
class OttomatLexer(RegexLexer):
    name='Ottomat'; aliases=['ottomat','ottmat']; filenames=['*.ottomat']; mimetypes=['text/x-ottomat']
    tokens={'root':[(r'\s+',Text.Whitespace),(r'\b(?:ottomat|ottmat|input|source|transform|algorithm|strategy|gate|output|profile|effect|import|let|emit)\b',Keyword),(r'\b(?:pure|read|record|required|optional|target_bps|curve|objective)\b',Keyword.Type),(r'[a-z][a-z0-9_.-]*@[0-9]+',Name.Class),(r'\b[0-9]+\b',Number.Integer),(r'=',Operator),(r'[a-zA-Z][a-zA-Z0-9_.-]*',Name),(r'.',Error)]}
def html(source):
    return highlight(source,OttomatLexer(),HtmlFormatter(cssclass='ottomat',nowrap=False))
