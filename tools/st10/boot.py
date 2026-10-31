"""Bootstrap payload.

The loader copies these bytes to FA40 and jumps there. The payload is
position-independent: a relative loop walks the five characters that follow
it and writes each one to S0TBUF.
"""


class Image:
    name = "BOOT"

    def emit(self):
        return """$MOD167
$CASE
$SEGMENTED
NAME BOOT
PAYLD SECTION CODE AT 0FA40H
PAYLD_P PROC NEAR
\tMOV\tR0,#text
\tMOV\tR2,#5
loop:
\tMOVB\tRL1,[R0]
\tMOVB\t0FEB0H,RL1
\tADD\tR0,#1
\tSUB\tR2,#1
\tJMPR\tcc_NZ,loop
spin:
\tJMPR\tcc_UC,spin
text:
\tDB\t42H,4FH,4FH,54H,0AH
PAYLD_P ENDP
PAYLD ENDS
\tEND
"""


def build():
    return Image()
