#!/usr/bin/env python3
"""Build arXiv LaTeX source from docs/PAST_Research_Paper_v2.md.

Usage: python3 arxiv/build.py   (from repo root or arxiv/)
Produces arxiv/main.tex, then compiles with tectonic if available.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "docs" / "PAST_Research_Paper_v2.md"
OUT = HERE / "main.tex"

md = SRC.read_text()

# ---------------------------------------------------------------- markdown fixes
# 1c. pipes inside math break pandoc pipe tables
md = md.replace(r"$|\Delta P_{i,t}| \leq 1$", r"$\lvert \Delta P_{i,t} \rvert \leq 1$")
md = md.replace(r"($|\Delta P| \leq 1$)", r"($\lvert \Delta P \rvert \leq 1$)")

# 1d. sentence continuation after display equations
md = md.replace("$$\n\nWhere $S(\\mathbf{P}_t)$", "$$\n\nwhere $S(\\mathbf{P}_t)$")
md = md.replace("$$\n\nWhere $T_i$", "$$\n\nwhere $T_i$")
md = md.replace("$$\n\nWhere $\\lfloor", "$$\n\nwhere $\\lfloor")
md = md.replace("$$\n\nWhere:\n", "$$\n\nwhere:\n")

# 6. Split off front matter / abstract / references / appendix for hand layout
title_m = re.match(r"# (.+?)\n", md)
title = title_m.group(1)
abstract = re.search(r"## Abstract\n\n(.+?)\n\n---", md, re.S).group(1)
body = md[re.search(r"## 1\. Introduction", md).start():]
refs_start = body.index("## References")
appendix_start = body.index("## Appendix A")
refs_md = body[refs_start:appendix_start]
appendix_md = body[appendix_start:]
body = body[:refs_start]

# drop horizontal rules
body = re.sub(r"\n---\n", "\n", body)
appendix_md = re.sub(r"\n---\n", "\n", appendix_md)
# strip manual numbering from headings (LaTeX numbers them)
body = re.sub(r"^(#{2,4}) (\d+(\.\d+)*\.?) ", r"\1 ", body, flags=re.M)
appendix_md = appendix_md.replace("## Appendix A: ", "## ")

def pandoc(text: str) -> str:
    # Escape currency dollar signs so pandoc doesn't read them as math delimiters.
    # Walk the text: a `$...$` span counts as real math only if it contains a LaTeX-ish
    # character (\ _ ^ = { }); everything else is currency and gets escaped.
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "$" and (i == 0 or text[i-1] != "\\"):
            if i + 1 < n and text[i+1] == "$":          # display math $$...$$
                j = text.find("$$", i + 2)
                if j != -1:
                    out.append(text[i:j+2]); i = j + 2; continue
            j = text.find("$", i + 1)
            nl = text.find("\n", i + 1)
            if j != -1 and (nl == -1 or j < nl) and (re.search(r"[\\_^={}]", text[i+1:j]) or re.fullmatch(r"[A-Za-z]{1,2}", text[i+1:j])):
                out.append(text[i:j+1]); i = j + 1; continue
            out.append("\\$"); i += 1; continue
        out.append(c); i += 1
    text = "".join(out)
    r = subprocess.run(["pandoc", "-f", "markdown", "-t", "latex", "--wrap=none", "--shift-heading-level-by=-1"],
                       input=text, text=True, capture_output=True, check=True)
    return r.stdout

body_tex = pandoc(body)
appendix_tex = pandoc(appendix_md)
abstract_tex = pandoc(abstract)

# pandoc longtable -> keep, but drop the [] and use booktabs-friendly toprule already present
def fix_tables(t: str) -> str:
    t = t.replace(r"\begin{longtable}[]", r"\begin{longtable}")
    # centre longtables and shrink font
    t = t.replace(r"\begin{longtable}", "{\\small\n\\begin{longtable}")
    t = t.replace(r"\end{longtable}", "\\end{longtable}}")
    # breathing room between multi-line rows
    t = t.replace(r"\endlastfoot", "\\endlastfoot\n\\renewcommand{\\arraystretch}{1.15}")
    return t

body_tex = fix_tables(body_tex)
appendix_tex = fix_tables(appendix_tex)

# make monospace file paths breakable at / and _ so narrow table columns don't overprint
body_tex = re.sub(r"\\texttt\{(state/[^}]+)\}",
                  lambda m: r"\path{" + m.group(1).replace(r"\_", "_") + "}", body_tex)
# live-trade table: 8 columns is too dense — shrink to footnotesize for that one table
lt_start = body_tex.index(r"\subsection{Live Trading Record")
lt_tbl = body_tex.index("{\\small\n\\begin{longtable}", lt_start)
body_tex = body_tex[:lt_tbl] + "{\\scriptsize\n\\begin{longtable}" + body_tex[lt_tbl+len("{\\small\n\\begin{longtable}"):]

# citations: hook named references in the running text
cites = {
    "Schulman et al., 2017": r"\citep{schulman2017ppo}",
}
for k, v in cites.items():
    body_tex = body_tex.replace(f"({k})", v)
body_tex = body_tex.replace(r"\textbf{TradingAgents} (Tauric Research, 80k+ GitHub stars)",
                            r"\textbf{TradingAgents}~\citep{xiao2024tradingagents} (Tauric Research, 80k+ GitHub stars)")
body_tex = body_tex.replace(r"\textbf{AI Hedge Fund} (virattt, 51.7k stars)",
                            r"\textbf{AI Hedge Fund}~\citep{singh2025aihedgefund} (virattt, 51.7k stars)")
body_tex = body_tex.replace(r"\textbf{AI-Trader} (HKUDS, 21k stars)",
                            r"\textbf{AI-Trader}~\citep{fan2026aitrader} (HKUDS, 21k stars)")
body_tex = body_tex.replace("Microsoft's AutoGen, CrewAI, and LangGraph",
                            r"Microsoft's AutoGen~\citep{autogen2024}, CrewAI~\citep{crewai2024}, and LangGraph~\citep{langgraph2024}")
body_tex = body_tex.replace("alters their decision-making risk profiles, linguistic styles, and negotiation behaviors.",
                            r"alters their decision-making risk profiles, linguistic styles, and negotiation behaviors~\citep{hartley2025personality,wang2025risk}.")
body_tex = body_tex.replace("Direct Preference Optimization (DPO) and RLHF adjust",
                            r"Direct Preference Optimization (DPO)~\citep{rafailov2023dpo} and RLHF adjust")
body_tex = body_tex.replace("Alpha uses a 744B MoE model (GLM-5.2)",
                            r"Alpha uses a 744B MoE model (GLM-5.2~\citep{glm5})")
body_tex = body_tex.replace("via a standard 1--7 Likert scale.", r"via a standard 1--7 Likert scale~\citep{grable2003}.", 1)



# ---------------------------------------------------------------- references (thebibliography)
bib = r"""
\begin{thebibliography}{13}
\bibitem[Xiao et al.(2024)]{xiao2024tradingagents} Xiao, Y., Sun, E., Luo, D., Wang, W. (2024). TradingAgents: Multi-Agents LLM Financial Trading Framework. arXiv:2412.20138.
\bibitem[Singh(2025)]{singh2025aihedgefund} Singh, V. (2025). AI Hedge Fund. GitHub: \url{https://github.com/virattt/ai-hedge-fund}.
\bibitem[Fan et al.(2026)]{fan2026aitrader} Fan, T. et al. (2026). AI-Trader: 100\% Fully-Automated Agent-Native Trading. GitHub: \url{https://github.com/HKUDS/AI-Trader}.
\bibitem[Schulman et al.(2017)]{schulman2017ppo} Schulman, J., Wolski, F., Dhariwal, P., Radford, A., Klimov, O. (2017). Proximal Policy Optimization Algorithms. arXiv:1707.06347.
\bibitem[Rafailov et al.(2023)]{rafailov2023dpo} Rafailov, R., Sharma, A., Mitchell, E., Ermon, S., Manning, C.~D., Finn, C. (2023). Direct Preference Optimization: Your Language Model is Secretly a Reward Model. arXiv:2305.18290.
\bibitem[Hartley et al.(2025)]{hartley2025personality} Hartley, J., Hamill, C., Batra, D., Seddon, D., Okhrati, R., Khraishi, R. (2025). How Personality Traits Shape LLM Risk-Taking Behavior. \emph{Findings of the Association for Computational Linguistics: ACL 2025}, pp.~21068--21092.
\bibitem[Wang et al.(2025)]{wang2025risk} Wang, Y., Li, X., Chen, G. (2025). Risk Profiling and Modulation for LLMs. arXiv:2509.23058.
\bibitem[GLM-5 Team(2026)]{glm5} GLM-5 Team, Zeng, A., Lv, X., Hou, Z. et al. (2026). GLM-5: from Vibe Coding to Agentic Engineering. arXiv:2602.15763.
\bibitem[Grable and Lytton(2003)]{grable2003} Grable, J.~E., Lytton, R.~H. (2003). The Development of a Risk Assessment Instrument: A Follow-Up Study. \emph{Financial Services Review}, 12(3), 257--274.
\bibitem[Wu et al.(2024)]{autogen2024} Wu, Q. et al. (2024). AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation. arXiv:2308.08155.
\bibitem[CrewAI(2024)]{crewai2024} CrewAI (2024). CrewAI: Framework for Orchestrating Role-Playing Autonomous AI Agents. \url{https://github.com/crewAIInc/crewAI}.
\bibitem[LangChain(2024)]{langgraph2024} LangChain Inc. (2024). LangGraph: Building Stateful Multi-Actor Applications with LLMs. \url{https://github.com/langchain-ai/langgraph}.
\end{thebibliography}
"""

preamble = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{booktabs,longtable,array}
\usepackage{calc}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{tcolorbox}
\usepackage{natbib}
\usepackage[hidelinks]{hyperref}
\usepackage{url}
\usepackage{enumitem}
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\newenvironment{decisionbox}{\begin{tcolorbox}[colback=red!6,colframe=red!70!black,boxrule=0.8pt,arc=1pt,left=4pt,right=4pt,top=3pt,bottom=3pt]\small}{\end{tcolorbox}}
\setlength{\LTleft}{0pt}\setlength{\LTright}{0pt}
\setcounter{secnumdepth}{3}

\title{Tuning the Persona, Not the Weights:\\The PAST Framework for Personality-Adaptive Multi-Agent Trading Systems}
\author{John Tytko\\Independent Researcher\\\texttt{tytkojm@gmail.com}}
\date{September 2026 \quad (v2.4)}

\begin{document}
\maketitle

\begin{abstract}
""" + abstract_tex.strip() + r"""
\end{abstract}

"""

closing = r"""

\appendix
\section{Real-Time Personality Swap --- Aschenbrenner $\rightarrow$ Baker}
""" + appendix_tex.replace(r"\section{Real-Time Personality Swap --- Aschenbrenner → Baker}\label{real-time-personality-swap-aschenbrenner-baker}", "").strip() + r"""

\vspace{1em}
\noindent\emph{This research is for educational purposes. Past performance does not indicate future results. The Trading Arena uses real capital and accepts the risks of AI-driven trading. Code and backtest harness: \url{https://github.com/sloth1122/past-framework}.}

\end{document}
"""

tex = preamble + body_tex + bib + closing
# unicode arrows pandoc leaves through
tex = tex.replace("→", r"$\rightarrow$").replace("≥", r"$\geq$").replace("≤", r"$\leq$").replace("σ", r"$\sigma$").replace("−", "-").replace("±", r"$\pm$")
tex = tex.replace("✅", "").replace("⚠️", "")
OUT.write_text(tex)
print(f"wrote {OUT} ({len(tex.splitlines())} lines)")

if "--no-build" not in sys.argv:
    r = subprocess.run(["tectonic", "-X", "compile", "--keep-logs", str(OUT)], cwd=HERE, capture_output=True, text=True)
    print(r.stdout[-3000:], r.stderr[-3000:])
    sys.exit(r.returncode)
