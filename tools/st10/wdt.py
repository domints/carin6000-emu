"""Watchdog image.

The first run stores a marker and spins until the watchdog resets the chip.
The second run sees the marker, which a watchdog reset must leave in internal
RAM, disables the watchdog, and prints WDT.
"""


class Image:
    name = "WDT"

    def emit(self):
        return """$MOD167
$CASE
$SEGMENTED
NAME WDT
MAINSEC SECTION CODE AT 0000H
MAIN_P PROC NEAR
\tMOV\tR0,0F600H
\tCMP\tR0,#00A5H
\tJMPR\tcc_Z,second
\tMOV\tR0,#00A5H
\tMOV\t0F600H,R0
\tMOV\tR0,#0FF00H
\tMOV\t0FFAEH,R0
spin:
\tJMPR\tcc_UC,spin
second:
\tDISWDT
\tMOV\tR1,#0057H
\tMOVB\t0FEB0H,RL1
\tMOV\tR1,#0044H
\tMOVB\t0FEB0H,RL1
\tMOV\tR1,#0054H
\tMOVB\t0FEB0H,RL1
\tMOV\tR1,#000AH
\tMOVB\t0FEB0H,RL1
done:
\tJMPR\tcc_UC,done
MAIN_P ENDP
MAINSEC ENDS
\tEND
"""


def build():
    return Image()
