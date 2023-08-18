# interpolate between 2 shader
import re
import sys

def interpolate(str1, str2, ratio = -0.25):
    
    def replace(match):
        number1 = float(match.group(0))
        number2 = float(next(iter).group(0))
        average = (number1 + number2 * ratio) / (1+ratio)
        return str(round(average, 12))

    pattern = r'-?\d+(\.\d+)(e-?\d+)?'
    iter = re.finditer(pattern, str2)
    return re.sub(pattern, replace, str1)

if len(sys.argv) < 4:
    exit()
str1 = open(sys.argv[1]).read()
str2 = open(sys.argv[2]).read()
new = interpolate(str1, str2)
with open(sys.argv[3], "w") as f:
    f.write(new)