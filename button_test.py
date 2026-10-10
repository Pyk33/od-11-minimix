#!/usr/bin/env python3
"""
button_test.py – hittar COM/NO/NC på en tryckknapp med tre trådar, utan multimeter.

Koppling (Pi avstängd när du kopplar!):
  Tråd A  -> GND (t.ex. pin 20)
  Tråd B  -> GPIO22 (pin 15)
  Tråd C  -> GPIO23 (pin 16)
Kör sedan:  python3 button_test.py
"""
from gpiozero import Button

b = Button(22, pull_up=True)
c = Button(23, pull_up=True)


def read():
    # True = pinnen har kontakt med GND
    return b.is_pressed, c.is_pressed


input("Släpp knappen helt och tryck Enter... ")
rb, rc = read()
input("Håll knappen NEDTRYCKT och tryck Enter... ")
pb, pc = read()
print(f"\nVila:      B={int(rb)}  C={int(rc)}")
print(f"Nedtryckt: B={int(pb)}  C={int(pc)}\n")

state = {"B": (rb, pb), "C": (rc, pc)}
swap_to_on = [k for k, v in state.items() if v == (False, True)]
swap_to_off = [k for k, v in state.items() if v == (True, False)]
never = [k for k, v in state.items() if v == (False, False)]

if len(swap_to_on) == 1 and len(swap_to_off) == 1:
    print(f"Tråd A = COM, tråd {swap_to_on[0]} = NO, tråd {swap_to_off[0]} = NC")
elif len(swap_to_on) == 1 and len(never) == 1:
    print(f"Tråd A = NO, tråd {swap_to_on[0]} = COM, tråd {never[0]} = NC")
elif len(swap_to_off) == 1 and len(never) == 1:
    print(f"Tråd A = NC, tråd {swap_to_off[0]} = COM, tråd {never[0]} = NO")
else:
    print("Oväntat resultat. Kontrollera kopplingen och försök igen, eller byt vilken tråd som är A.")
