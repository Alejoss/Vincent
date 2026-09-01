---
title: "Reflections Upon Bitcoin's Block Size Debate"
source: "https://blog.lopp.net/reflections-upon-bitcoins-block-size-debate/"
author:
  - "[[Jameson Lopp]]"
published: 2026-07-01
created: 2026-08-04
description: "Analysis of the ideological split and narratives employed during Bitcoin's scaling debates."
tags:
  - "clippings"
---
![Reflections Upon Bitcoin's Block Size Debate](https://blog.lopp.net/content/images/size/w1140/2026/06/block-size-debate.png)

Reflections Upon Bitcoin's Block Size Debate

It has been nearly 9 years since the conclusion of the block size debate and ensuing fork war. Why bring it up now? This essay is actually a precursor to a future post about more recent conflicts and governance battles in Bitcoin, because I’m seeing parallels and wondering if the social dynamics and game theory at play will doom us to repeat similar ideological battles on a regular basis. In some sense this is not so different from what tends to happen in other voluntary organizations. For example, look at how many “denominations” (forks) of Christianity have come into existence as it has splintered over the smallest of disagreements. Or look at how many “distributions” (forks) of Linux have been developed as disagreements festered over how to prioritize development of an operating system. Consensus based systems do seem to fracture over time.

I’ve said several times over the years that I find the governance of Bitcoin, which is an anarchic system, to be even more interesting than its technical aspects. However, in order to understand Bitcoin governance one needs a solid grasp of the technicals so that you can model the incentives and game theory at play.

For example: Bitcoin's ethos relies heavily upon the concept of individual sovereignty. Yet, as they say, no man is an island.

Because of Bitcoin's ethos of decentralization, whenever a group of people coordinate to improve the system, those who dissent will often cry foul with claims of centralization. Bitcoin Core is an easy target for such naive claims, as a quick glance at the project makes it look like an organization that is "controlling" Bitcoin whereas it's better thought of as a process through which the schelling point of human consensus flows in order to determine machine consensus for the network.

I feel uniquely positioned to discuss the block size debate because I found myself participating on both sides over the years. In 2015 I was solidly a big blocker as I had come from a “big data” background in which I had been impressed with the perspective that high throughput capability leads to a better user experience and that throughput bottlenecks lead to poor UX and thus loss of users. I was also particularly upset with how discourse was being manipulated by moderators on discussion platforms.

![](https://x.com/i/status/630512763153051648)

Then in 2016 I changed my mind as I learned more about SegWit and learned how difficult it was to index the (relatively small) blockchain since it was my primary responsibility as an infrastructure engineer at BitGo. As we added support for various “high throughput” blockchains I saw how syncing and indexing became even more difficult. It became clear to me that if it was challenging for enterprises with specialist engineers to run infrastructure for these blockchains, there was no chance for the average user to run their own sovereign infrastructure.

As such, I’m sympathetic to both sides of the debate. Participants on both sides did and said nasty things of which I do not approve. I was personally affected by such activities - my home internet connection got DoS attacked and taken offline for most of a day as a result of me running a Bitcoin XT (big blocker) node in 2015. Two years later [I was swatted](https://blog.lopp.net/reflections-upon-a-swatting/) for my controversial “small blocker” statements on Twitter. Also, I believe that the motives of the people on each side of the debate (except for Bitmain) were honest - they truly believed that they knew what was best for the future direction of Bitcoin’s development.

We only found out late in the conflict that it was not purely ideological on both sides. The big blocker side was backed by Bitmain because [SegWit may have broken their covert ASICboost mining advantage](https://farside.co.uk/the-blocksize-war-chapter-14-asicboost/?ref=blog.lopp.net). I suspect that no one on either side was aware of this until Greg Maxwell discovered it; Bitmain kept it secret because revealing their incentive would have undermined their position.

The debate was incredibly complex, both technical and philosophical, though after years of participating I came to distill it down to one simple question: *should Bitcoin be optimized for low cost of transacting at the potential expense of higher cost of auditing the system (running a full node) or should Bitcoin be optimized for low cost of auditing the system at the potential expense of higher cost of transacting?*

The scaling debates were so lengthy, contentious, and formative to the future direction of Bitcoin development that each side of the debate ended up writing a book about what happened from their perspective. It’s worth comparing and contrasting the views of each side because, while history does not repeat, it does tend to rhyme.

## Big Blocks vs Small Blocks

Jonathan Bier's *The Blocksize War* tells the story of Bitcoin surviving a hostile and reckless governance challenge. The central question is: who gets to change Bitcoin’s rules? His answer is: not miners, not companies, not famous developers, not meetings of industry leaders, but economically active users who choose what rules their nodes enforce and in the event of a split, which coin they choose to hold.

Roger Ver & Steve Patterson’s *Hijacking Bitcoin* tells the same period as a betrayal of Bitcoin’s original mission. The central question is: was Bitcoin supposed to be peer-to-peer cash, and was that vision deliberately derailed? Their answer is: yes; BTC was steered away from low-fee everyday payments toward “digital gold” and settlement-layer ideology by a small, influential group.

In short, small blockers saw victory as a win for user sovereignty; big blockers see their loss as the result of project capture.

## What Was the War About?

*The Blocksize War* says the surface issue was block data capacity, but the deeper issue was “who controls Bitcoin's protocol rules.” The book covers the war from August 2015 to November 2017, presents a chronology of major events, and says it draws on discussions with key players from both sides. That framing matters: block size is important, but Bier's real subject is governance under adversarial pressure.

*Hijacking Bitcoin* frames the dispute differently. It claims Bitcoin was promised as a liberating alternative to state money but was “captured and changed for the worse,” and that the book challenges narratives around whether Bitcoin is decentralized, whether it should be digital gold or digital cash, and whether its original design had scaling problems. The book is described by its authors as being about “how a small group of insiders altered the course of digital currency” and Bitcoin's “deviation from its original design” through censorship and control.

Thus, each side does not merely disagree over what Bitcoin’s block size should be. They disagree over the fundamental purpose and use cases of Bitcoin.

## The Original Bitcoin Vision

Ver leans heavily on the whitepaper's description of Bitcoin as **“a peer-to-peer electronic cash system.”** The whitepaper’s abstract describes online payments sent directly between parties without a financial institution. For *Hijacking Bitcoin*, that phrase is not just branding; it is the project’s purpose. Cheap, on-chain, self-custodial payments are treated as indisputable attributes necessary for Bitcoin to uphold its initial promise.

Bier does not deny the origin story of p2p electronic cash, but he subordinates that goal to a different priority: **immutability of rules and user verification**. In Bier's telling, Bitcoin's uniqueness is not just that it can make payments, but that no coordinated group can easily change the rules out from under users.

Thus we see the philosophical split:

**Ver:** *Bitcoin fails if ordinary people cannot cheaply use it as electronic cash.*

**Bier:** *Bitcoin fails if ordinary users cannot independently reject unwanted rule changes.*

## How Bier portrays Big Blockers

*The Blocksize War* gives the big blockers legitimate motivations at the start. In his account, Bitcoin XT was released by Mike Hearn and supported by Gavin Andresen because blocks were filling and fees were rising, and Bitcoin looked to be on a path to become too expensive or unreliable for a cheap global payment network. You can get a good sense for the big blocker concerns from reading Mike Hearn's [declaration of Bitcoin as a failed experiment](https://medium.com/mike-hearn/the-resolution-of-the-bitcoin-experiment-dabb30201f7?ref=blog.lopp.net). Bier does not dismiss these concerns as being incorrect.

But Bier increasingly portrays the big-block side as strategically clumsy and technically weak. Bitcoin XT, Bitcoin Classic, Bitcoin Unlimited, Bitcoin Cash, and SegWit2x become, in his view, successive failed attempts to force a rule change without broad user consensus. His treatment of Bitcoin Unlimited is especially harsh: he calls it complex, technically flawed, and a major strategic error for large blockers.

By the end, Bier's interpretation is clear: the large blockers had money, miners, companies, and prominent personalities, but they could not command the network. When SegWit2x was abandoned in November 2017, he calls it a victory for small blockers and, more importantly, for the principle that ordinary users ultimately decide which rules they accept.

## How Ver Portrays Small Blockers

*Hijacking Bitcoin* flips the script by focusing on ethos rather than technicals. It portrays the small block side not as defenders of decentralization, but as the group that **changed Bitcoin's purpose** while claiming to protect it. The book airs a litany of grievances including censorship, social media engineering, information control, “centralizing control,” and a move away from the original design.

In this narrative, high fees were not an unfortunate growing pain; they were the result of an artificial bottleneck. Keeping blocks small pushed people away from direct on-chain use, weakened merchant adoption, and made Bitcoin less useful as cash. Lightning and custodial layers are treated with suspicion because they can shift activity away from the base chain and toward more complex or intermediary-dependent systems.

Where Bier sees restraint, Ver sees sabotage. Where Bier sees conservative engineering, Ver sees a successful campaign to redefine Bitcoin from spendable money into a settlement asset.

## SegWit & Lightning: Elegant Solution or Misdirection?

Bier presents SegWit as a clever soft-fork compromise. It increased the effective block size, fixed transaction malleability, fixed the sighash scaling problem, and avoided a contentious hard fork. He also presents Lightning as a plausible layer-two scaling path: instead of broadcasting every small payment to every node, users could make many payments through channels and settle fewer transactions on-chain. This is a sensible engineering solution, as it's the same way that the internet itself was scaled via many layers of networking protocols.

Ver sees the same move as part of the hijacking. From his perspective, SegWit and Lightning helped justify not increasing the block size enough for everyday on-chain payments. The objection is not only technical; it is political. He argues that BTC was reoriented away from being cash and toward becoming a high-fee settlement network, with users pushed toward second-layer or custodial arrangements.

Put simply:

**Bier:** *SegWit + Lightning preserved decentralization while scaling prudently.*

**Ver:** *SegWit + Lightning helped bury the original low-fee cash design.*

## Bitcoin Cash: Failed Fork or Preserved Purpose?

For Bier, Bitcoin Cash is the endpoint of the big block campaign after it failed to win consensus on BTC. Bitcoin Cash is a hard forked chain with a larger block limit and no SegWit, launched after the large block faction gave up trying to persuade developers of existing Bitcoin clients to implement a block size increase. In his conclusion, he argues BCH never gained traction relative to BTC, underperformed, and later split again, which he treats as evidence supporting the small-block concern that contentious hard forks fragment communities.

For Ver, Bitcoin Cash is not merely an altcoin born from defeat. It is closer to an attempted rescue operation: a chain meant to preserve the peer-to-peer cash use case after BTC, in their view, had been captured. In their narrative, BCH represents continuity with Bitcoin’s early promise, while BTC represents the altered path.

This is why the naming dispute was so contentious and for many years, supporters of Bitcoin Cash would claim that it was “the real Bitcoin.”

Small blockers: **BTC kept the rules, network effect, and legitimacy.**

Big blockers: **BCH kept the purpose.**

## Censorship and Social Control

*The Blocksize War* discusses politics, propaganda, personalities, pressure campaigns, and factionalism, but his final framing is still mostly about consensus rules. The system worked because users could refuse a rule change. I can tell you from personal experience that there are many dynamics the book doesn’t cover, especially with regard to communications and strategizing in private channels. The public debates were only part of the battle for control over the future of Bitcoin.

*Hijacking Bitcoin* puts much more weight on information control: Reddit moderation, forum control, social media narratives, reputational attacks, and the dominance of Bitcoin Core as the reference implementation. It explicitly says the true history is obscured by “heavy censorship, social media engineering, and tight information controls.”

This creates a deep disagreement about the meaning of “users chose Bitcoin’s future.”

Bier’s implicit view: users rejected large-block hard forks.

Ver’s implicit view: users’ choices were shaped by censorship, branding control, and narrative capture, so the “market chose BTC” story is incomplete.

## Where Both Sides Agree

They agree on more than you might suspect.

Both books agree the block size war was not a minor engineering dispute. It was a fight over Bitcoin’s identity, governance, and future.

Both agree the big blockers wanted more on-chain capacity to keep fees low and preserve Bitcoin’s usefulness for payments.

Both agree the small blockers prioritized caution, decentralization, and resistance to contentious hard forks.

Both agree the 2015 - 2017 period was decisive, culminating in SegWit, Bitcoin Cash, and the collapse of SegWit2x.

The real disagreement is interpretive: was the outcome a defense of decentralization, or a successful hijacking of the project’s mission?

## Strengths and Weaknesses

Bier is stronger on the mechanics of the war. He is better at explaining the sequence of proposals, why particular clients failed, why miners could not simply dictate rules, and why the New York Agreement/SegWit2x approach collapsed. His account is detailed and, despite its small-block sympathy, it sometimes concedes uncertainty. Near the end, he explicitly says the small-block victory does not prove small blockers were right on the narrow block size question, and that perhaps a moderate increase could have helped Bitcoin retain more merchant adoption. That concession makes Bier more nuanced than a simple victory lap.

Ver is stronger on the moral grievance and lost-use-case argument. He forces the reader to confront a real problem: BTC did move away from the early “cheap payments for the world” story, and many ordinary users now interact through exchanges, custodians, or layers rather than frequent self-custodial base-chain payments. The critique is especially powerful if you think payment utility, not just store-of-value credibility, is essential to Bitcoin's purpose.

But *Hijacking Bitcoin* is also more polemical. Its "capture" framing can over-compress a messy, decentralized conflict into a story of villains and betrayal. Bier's weakness is the opposite: his governance framing can underplay the seriousness of censorship allegations and the possibility that “users chose” is not a clean explanation when communication channels and brand legitimacy are contested.

While there was certainly plenty of control enforced by owners of centralized Bitcoin discussion platforms, I was rather incredulous of the censorship claims. There were plenty of neutral platforms like Twitter / Facebook / YouTube upon which the debates raged for years; I felt that anyone who cared about the debate was more than capable of finding the information and arguments from each side. I even penned a lengthy article on this subject in 2017:

## Final Takeaways

**Bier is probably right that Bitcoin demonstrated a remarkable resistance to coercive rule changes.** Miners, companies, famous developers, and industry meetings could not force a hard fork onto users who did not want it.

**Ver is probably right that something important was lost.** The Bitcoin that emerged from the war was less focused on cheap everyday on-chain payments than the Bitcoin many early adopters believed they were building.

But the reality is that the predominant narrative for Bitcoin adoption has changed many times throughout its history; I suspect it’s naive to expect Bitcoin to retain the same narrative for any length of time while it’s still in the growth and evolutionary phases of its development. Nic Carter penned a great essay about changing narratives years ago, and I’d argue that the narratives have again changed in the time since it was published.

Bitcoin remains a fascinating system. I’ve argued that it’s not possible for anyone to fully understand.

One reason we can't fully understand Bitcoin is because it’s still relatively young and adoption levels are still low. As adoption continues, new cohorts will enter and contribute their own perspectives as to what Bitcoin should be and what use cases it should optimize to serve.

This is why I believe, as long as Bitcoin is still growing, we should expect more battles over how the protocol should evolve and what trade-offs should be accepted in order to improve the system in different ways.