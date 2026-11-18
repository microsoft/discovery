We're starting a new moisturizer project and I'd like your help planning the lab work.

It's a lightweight daily face lotion for normal-to-dry skin. It needs to feel light and non-sticky, pump easily, and still deliver real hydration and barrier benefit. It's a mass-market product, so cost matters.

Here's what it has to hit, all in the same formulation:

  Skin hydration (corneometer), day 28         at least 40 % increase
  TEWL, day 28                                 at least 25 % reduction
  Viscosity                                    3,000 - 10,000 cP
  Tack (trained panel, 1-10, lower is better)  at most 3.5
  Accelerated stability score (0-100)          at least 90
  Raw-material cost                            at most 4.6 $/kg of finished product

Hydration and TEWL are measured on a small panel after 28 days of twice-daily use.

We'll build it on a standard O/W chassis. You can set these nine things, within these limits (water makes up the balance; preservative and buffer are fixed and you can ignore them):

  Glycerin                     0 - 10 % w/w
  Niacinamide                  0 - 10 % w/w
  Hyaluronic acid              0 - 0.5 % w/w
  Peptide complex              0 - 1 % w/w
  Centella asiatica extract    0 - 5 % w/w
  Ceramide NP                  0 - 0.3 % w/w
  Emollient blend              0 - 20 % w/w
  Carbomer ("thickener")       0 - 1 % w/w
  pH                           4 - 7

The emollient blend is a fixed mix of squalane, dimethicone, caprylic/capric triglyceride and shea. Keep total additions low enough that water stays above 50 %.

The papers on the skincare shelf are what we have on these ingredients. We have no previous data on this chassis, so treat it as a clean start.

The lab can make and test 5 formulations per round, and we have budget for 4 rounds - 20 in total. Results come back after each round.

For round 1, propose 5 formulations. For each, give one sentence on why you're running it.

Before the formulations, tell me briefly how you're approaching the problem and what you expect the hardest trade-off to be.

Please don't invent data or cite anything you haven't actually read. If you're unsure, say so.

End with this JSON so the lab can batch it:

{
  "batch": <n>,
  "experiments": [
    {"glycerin": .., "niacinamide": .., "hyaluronic_acid": .., "peptide": ..,
     "centella": .., "ceramide": .., "emollient": .., "thickener": .., "pH": ..,
     "why": "<one sentence>"}
  ]
}
