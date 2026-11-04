import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FP = os.path.join(HERE, "for_poster")

RENAMES = {
    "agent_environment.tex": [
        (r"\cariconV", r"\aeCarV"), (r"\caricon", r"\aeCar"),
        (r"\busicon", r"\aeBus"),
        (r"\sigheadred", r"\aeSigRed"), (r"\sigheadgreen", r"\aeSigGreen"),
    ],
    "multi_agent.tex": [
        (r"\cariconV", r"\maCarV"), (r"\caricon", r"\maCar"),
        (r"\busicon", r"\maBus"),
        (r"\sigheadred", r"\maSigRed"), (r"\sigheadgreen", r"\maSigGreen"),
    ],
    "green_extension_stages.tex": [
        (r"\cariconV", r"\geCarV"), (r"\caricon", r"\geCar"),
        (r"\busicon", r"\geBus"), (r"\sigamber", r"\geSigAmber"),
        (r"\siggreen", r"\geSigGreen"), (r"\sigred", r"\geSigRed"),
        (r"\extring", r"\geExtRing"),
    ],
    "red_truncation_stages.tex": [
        (r"\cariconV", r"\rtCarV"), (r"\caricon", r"\rtCar"),
        (r"\busicon", r"\rtBus"),
        (r"\siggreen", r"\rtSigGreen"), (r"\sigred", r"\rtSigRed"),
    ],
    "green_wave_5int.tex": [],
}

def snippet(fname):
    s = open(os.path.join(FP, fname), encoding="utf-8").read()
    i = s.find(r"\begin{tikzpicture}")
    j = s.find(r"\end{tikzpicture}") + len(r"\end{tikzpicture}")
    body = s[i:j]
    for a, b in RENAMES[fname]:
        body = body.replace(a, b)
    # agent's cariconV is declared with 3 args but used with 2
    if fname == "agent_environment.tex":
        body = body.replace(r"\newcommand{\aeCarV}[3]", r"\newcommand{\aeCarV}[2]")
    return body

p = os.path.join(HERE, "poster_tap2026.tex")
shutil.copyfile(p, p + ".bak_before_inline")
s = open(p, encoding="utf-8").read()

# add colours used by the diagrams
colours = (r"\definecolor{busblue}{RGB}{30,90,180}" + "\n"
           r"\definecolor{busyellow}{RGB}{255,205,60}" + "\n"
           r"\definecolor{amber}{RGB}{230,160,30}" + "\n"
           r"\definecolor{crossgrey}{RGB}{214,214,214}" + "\n")
s = s.replace(r"\definecolor{teal}{RGB}{0,128,128}", r"\definecolor{teal}{RGB}{0,128,128}" + "\n" + colours)

repl = {
    r"\includegraphics[width=\linewidth]{for_poster/agent_environment.pdf}":
        lambda: r"\resizebox{\linewidth}{!}{" + "\n" + snippet("agent_environment.tex") + "\n}",
    r"\includegraphics[width=\linewidth]{for_poster/multi_agent.pdf}":
        lambda: r"\resizebox{\linewidth}{!}{" + "\n" + snippet("multi_agent.tex") + "\n}",
    r"\includegraphics[height=160mm]{for_poster/green_extension_stages.pdf}":
        lambda: r"\resizebox{\linewidth}{!}{" + "\n" + snippet("green_extension_stages.tex") + "\n}",
    r"\includegraphics[height=160mm]{for_poster/red_truncation_stages.pdf}":
        lambda: r"\resizebox{\linewidth}{!}{" + "\n" + snippet("red_truncation_stages.tex") + "\n}",
    r"\includegraphics[width=\linewidth]{for_poster/green_wave_3int.pdf}":
        lambda: r"\resizebox{\linewidth}{!}{" + "\n" + snippet("green_wave_5int.tex") + "\n}",
}
for k, fn in repl.items():
    assert k in s, "missing anchor: " + k
    s = s.replace(k, fn())

open(p, "w", encoding="utf-8").write(s)
print("inlined diagrams; backup:", os.path.basename(p + ".bak_before_inline"))
