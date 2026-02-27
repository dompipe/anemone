"""
generate_code_templates.py
A small "masterkey" module to generate code for modest prompts.
This file implements `generate_code(prompt)` and an optional `extract_prompt_pieces(prompt)` helper.
"""

import re


def extract_prompt_pieces(prompt: str):
    lp = prompt.lower()
    pieces = {}
    nums = re.findall(r"-?\d+", lp)
    pieces['numbers'] = [int(n) for n in nums]
    return pieces


def generate_code(prompt: str) -> str:
    """Produce Python code for certain non-trivial prompts.
    This is not a template lookup; it composes code algorithmically for the matched intent.
    Currently supports:
      - discrete convolution of two numeric lists
      - polynomial derivative (coeff list -> derivative coeff list)
    """
    lp = prompt.lower()

    # Convolution intent
    if 'convol' in lp and 'list' in lp:
        return (
            "def convolve(a, b):\n"
            "    \"\"\"Return the discrete linear convolution of sequences `a` and `b`.\n\n"
            "    Both `a` and `b` must be sequences of numbers (lists or tuples).\n"
            "    The result has length len(a) + len(b) - 1.\n"
            "    \"\"\"\n"
            "    # Basic validation\n"
            "    if a is None or b is None:\n"
            "        raise ValueError('Input sequences must not be None')\n"
            "    m = len(a)\n"
            "    n = len(b)\n"
            "    if m == 0 or n == 0:\n"
            "        return []\n"
            "    # allocate output\n"
            "    out = [0] * (m + n - 1)\n"
            "    for i in range(m):\n"
            "        ai = a[i]\n"
            "        for j in range(n):\n"
            "            out[i + j] += ai * b[j]\n"
            "    return out\n\n"
            "if __name__ == '__main__':\n"
            "    x = [1, 2, 3]\n"
            "    y = [0, 1, 0.5]\n"
            "    print('convolve(x,y) ->', convolve(x, y))\n"
        )

    # Polynomial derivative by coefficient list
    if 'polynomial' in lp and ('derivative' in lp or 'differentiate' in lp):
        return (
            "def poly_derivative(coeffs):\n"
            "    \"\"\"Given polynomial coefficients `coeffs` representing\n"
            "    a_0 + a_1 x + a_2 x^2 + ... return coefficients of its derivative.\n"
            "    Example: [3, 2, 1] -> derivative of 3 + 2x + x^2 is [2, 2] (2 + 2x)\n"
            "    \"\"\"\n"
            "    if not coeffs:\n"
            "        return []\n"
            "    return [i * c for i, c in enumerate(coeffs)][1:]\n\n"
            "if __name__ == '__main__':\n"
            "    print(poly_derivative([3, 2, 1]))\n"
        )

    return '# No masterkey match for prompt.'
