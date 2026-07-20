"""
Evals de Xframe.

Siguen el patrón de `ee/hogai/eval/` de PostHog: pytest como runner, descubrimiento por
`eval_*.py` para que no corran con la suite unitaria, scorers graduados y datasets
tipados en el propio repositorio.

    pytest evals -m evals                 # todo
    pytest evals -m evals --eval thriller # solo los casos que contengan "thriller"
    pytest evals/eval_script.py -m evals   # una suite

Cuestan dinero y llaman a modelos reales. Están excluidos del CI rápido con
`-m "not evals"`; ver el README.
"""
