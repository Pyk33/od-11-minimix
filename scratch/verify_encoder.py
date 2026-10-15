#!/usr/bin/env python3
"""
Verify PCD math and hole coordinates for encoder E38S6G5-600B.
"""
import math

c1 = 8.5   # korta sträckan mellan hål i samma par
c2 = 19.0  # längre sträckan mellan närmsta hål i intilliggande par

# Lös för vinkeln u = alpha / 2:
# 2*R*sin(u) = 8.5
# 2*R*sin(60 - u) = 19.0
# sin(60 - u) / sin(u) = 19.0 / 8.5
ratio = c2 / c1
# sin(60)*cot(u) - cos(60) = ratio
# (sqrt(3)/2)*cot(u) - 0.5 = ratio
cot_u = (ratio + 0.5) / (math.sqrt(3) / 2.0)
u_rad = math.atan(1.0 / cot_u)
alpha_deg = math.degrees(2 * u_rad)
R = (c1 / 2.0) / math.sin(u_rad)
D = 2 * R

print(f"Beräknad delningsdiameter (PCD): {D:.2f} mm (R = {R:.2f} mm)")
print(f"Vinkel mellan hål i par (alpha): {alpha_deg:.2f}°")
print(f"Vinkel mellan par (beta): {120.0 - alpha_deg:.2f}°")

# Kontrollmät kordor:
test_c1 = 2 * R * math.sin(math.radians(alpha_deg / 2))
test_c2 = 2 * R * math.sin(math.radians((120 - alpha_deg) / 2))
print(f"Kontroll c1: {test_c1:.2f} mm (ska vara 8.5)")
print(f"Kontroll c2: {test_c2:.2f} mm (ska vara 19.0)")
