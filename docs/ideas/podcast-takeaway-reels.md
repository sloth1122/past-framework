# Idea: Podcast Takeaway Reels

*Captured 2026-08-15. Status: raw brainstorm, not committed to.*

**One line:** An app that turns a 2-hour podcast into a single 60–90 second produced video
containing the 3–4 statements that actually mattered, formatted to drop straight into an
iMessage thread.

---

## 1. What's actually new here

The AI-clip space is crowded but every tool in it is pointed the other way.

| | Existing tools | This |
|---|---|---|
| **User** | Creator repurposing *their own* show | Listener sharing *someone else's* show |
| **Output unit** | N standalone viral clips | **One** digest reel, 3–4 takeaways stitched |
| **Destination** | TikTok / Reels / Shorts, public | iMessage thread, 1:1 or small group |
| **Goal** | Reach | "You need to hear this part" |

Opus Clip, Choppity, Vizard, Klap, Ssemble all sit in the top-right of the creator quadrant.
Snipd is the only one near the listener quadrant, and it's audio-first, in-app, and one
moment per snip — it never produces the *episode digest* as a single artifact.

**The format is the invention.** Nobody makes the "here are the 4 things this episode said"
reel. It's the podcast equivalent of a book's highlight page, and it's the thing you'd
actually text a friend. Everything else is downstream of nailing that.

## 2. The bet, stated so it can be falsified

Current behavior when someone loves an episode: send the link, maybe "start at 42:00."
Recipient listens ~10% of the time.

The bet: a produced 90s video that autoplays in the thread converts dramatically better —
recipient *watches* rather than bookmarks-and-forgets, and replies. If that lift isn't
large, there is no company here, just a feature.

**Test it in week one, no code.** Hand-cut reels for 20 episodes. Send to real friends.
Measure two numbers only: watch-through rate, and reply rate. Compare against a control
group who just get the link + timestamp. If produced-video doesn't roughly triple reply
rate, kill it or repoint it.

## 3. Pipeline

```
episode → transcript (diarized, word-level ts) → semantic beat segmentation
        → takeaway scoring → boundary snapping → script/order → render → share
```

**Transcript.** Whisper-class with diarization and word-level timestamps. Word-level is
non-negotiable — sentence-level timestamps produce cuts that clip the first syllable, and
that single artifact makes the whole thing feel cheap.

**Segmentation.** Don't chunk by fixed window. Chunk by *rhetorical beat* — a claim and its
support, a story, an exchange. A takeaway that starts mid-argument is unusable no matter how
good the sentence is.

**Scoring — this is the whole product.** Naive "find the highlights" prompting returns
generic motivational pablum. Score explicitly for:
- a **claim with a mechanism** ("X because Y"), not a conclusion alone
- **counterintuitive** — contradicts what a smart listener would have assumed
- **specific** — has a number, a name, a date, a concrete instance
- **self-contained** — survives with zero preceding context
- **actionable or reframing** — changes what you'd do or how you'd see it

And a hard negative list: intros, sponsor reads, "that's a great question," agreement
noises, anything requiring a pronoun antecedent from three minutes earlier.

**Boundary snapping.** Cut on breath boundaries, not word boundaries. Pull in ~200ms of
lead-in room. Fade the tail rather than hard-cutting mid-decay.

**Ordering.** Not chronological — lead with the strongest. A digest reel gets 3 seconds to
justify itself in a text thread.

## 4. Where does the video come from

Most podcasts are audio-only in RSS. Three options:

1. **Match the YouTube upload** and cut real video. Best-looking, but needs
   RSS-episode↔YouTube-upload matching plus timestamp alignment (the two cuts differ), and
   it puts you squarely inside YouTube's ToS. Don't start here.
2. **Synthesize an audiogram** — waveform or animated typography, show art, speaker
   headshot, kinetic captions, per-takeaway title cards. Fully controllable, no scraping,
   and you own the visual language.
3. Licensed video from partner shows. That's the phase-3 answer.

**Start with (2).** The design of the audiogram becomes the brand — every reel sent is an
ad, so the template has to be genuinely beautiful, not "AI caption overlay." Budget real
design effort here; it's the marketing spend.

## 5. iMessage specifics

You cannot send iMessages programmatically. The mechanism is:
- an **iMessage App Extension** so the reel is pickable from the drawer inside a thread, and
- the **iOS Share Sheet** as the fallback path.

Practical constraints that decide the render target:
- iMessage recompresses video hard. Render 1080×1920, target ~15–25MB, so what lands in the
  thread doesn't look like a fax.
- It must **autoplay inline** in the thread. A file that shows as an attachment card is dead.
- Burned-in captions, always — these get watched muted.

**Video file vs. link.** File = zero friction, but no attribution and no growth loop.
Link = rich preview, attribution back to the show, analytics, and an install prompt.
Probably: send the file, with a tasteful end card carrying show name + a short link.

## 6. Growth loop

The product *is* the acquisition channel:

```
friend receives reel in thread → watches (it's good) → taps end card
   → web player, full episode linked → "make one from any episode" → install
```

Dark social is already where podcast discovery actually happens — word of mouth is the #1
discovery mechanism for shows. This just gives that behavior a much better artifact. That
also means the private/1:1 framing is a *feature*, not a limitation on reach.

## 7. Cost and latency

A 2-hour episode is expensive to transcribe and reason over on demand, and nobody waits
four minutes to send a text.

**Lever: precompute.** Nightly-process the top ~2,000 shows on release. Then the common case
is cache-hit — the takeaways already exist, and only the render is on demand (seconds). It
also collapses marginal cost per share to near zero and lets you show a feed of
"ready-to-send" reels for shows the user follows, which is a much better cold-start than an
empty upload box.

Long-tail / niche shows fall back to on-demand with an honest progress state.

## 8. The real risk: rights

You are redistributing copyrighted audio you don't own. Be clear-eyed:

- Short excerpts + attribution + a link driving traffic back to the show is the defensible
  posture (roughly Snipd's).
- Private 1:1 sharing is a much better position than a public ad-supported feed built on
  other people's IP. **Do not build the public feed.** It converts a tolerable practice into
  an obvious target.
- Cap total excerpt length per episode. Attribute prominently. Honor takedowns instantly and
  build the mechanism *before* you need it.
- Podcasters are the natural allies here, not opponents — this drives them listeners. Get
  3–5 mid-size shows to publicly endorse it early; that's both distribution and cover.

## 9. Business model

- **Consumer freemium** as the wedge: free tier watermarked, N shares/month;
  ~$8–12/mo for unwatermarked, custom styling, longer reels, multi-episode digests.
- **The actual business is the B2B flip:** podcast networks pay to have their catalog
  pre-processed and branded, because listener-to-friend private shares are their highest-
  intent acquisition channel and they currently have zero instrumentation on it. You'd be
  selling them measurable dark social. Consumer app is the wedge and the data moat.

## 10. First four weeks

1. **Week 1 — concierge.** Hand-cut 20 reels, send to real threads, measure watch-through
   and reply rate vs. link control. Decision gate.
2. **Week 2 — the picker.** Build only the scoring pass. Run it against episodes you know
   well and grade its picks against your own by hand. This is the only hard technical
   problem; if the model can't beat you at picking, nothing downstream matters.
3. **Week 3 — one beautiful template.** Not five. One, designed properly.
4. **Week 4 — share path.** iMessage extension + share sheet, 10 friendly users, watch the
   loop actually close.

## Open questions

- Does the sender want to **curate** (pick 3 of 8 candidates) or receive a finished cut?
  Curation raises quality and ownership but adds friction to a "text a friend" action.
  Guess: finished cut by default, one tap to swap a takeaway.
- Personalization to *recipient* — same episode, different cut for different friends. Very
  strong if it works, possibly over-engineering for v1.
- Does this generalize past podcasts to lectures, earnings calls, long YouTube interviews?
  Probably, but resist it until the wedge works.
