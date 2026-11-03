# Parsing references (Milestone 2)

Spec: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing

| Topic | Reference | Used for |
|---|---|---|
| BibTeX | https://ctan.org/pkg/bibtex | `.bib` syntax, only cited entries are kept |
| natbib | https://ctan.org/pkg/natbib | `\bibitem` lists in `.bbl` files |
| biblatex | https://ctan.org/pkg/biblatex | `\entry` records in `.bbl` files |
| REVTeX | https://ctan.org/pkg/revtex | `\bibinfo{field}{value}` in `.bbl` files |
| amsmath | https://ctan.org/pkg/amsmath | `align` to `aligned` inside `equation` |
| Python `re` | https://docs.python.org/3/library/re.html | Cleanup, sentence splitting, `\bibitem` conversion |
| Python `multiprocessing` | https://docs.python.org/3/library/multiprocessing.html | One parser worker per CPU |
| Apache Parquet | https://parquet.apache.org/docs/ | Output tables |
| Hugging Face dataset configuration | https://huggingface.co/docs/hub/datasets-manual-configuration | `configs` in the dataset card |
