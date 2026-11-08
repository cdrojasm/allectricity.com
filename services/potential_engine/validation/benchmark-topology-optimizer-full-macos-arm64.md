# Topology optimizer benchmark

192 runs: 4 scenarios x 6 seeds x 8 strategies, a cap of 150 solver calls each. Same scenario, same starting seeds and same cap for every strategy. Execution used 15 workers.

## Overall

| strategy | feasible (95% CI) | mean cost (M) | mean regret | found the best | rank | calls | time units | vs descent (better/equal/worse, p) | mean change [95%] | vs alns (better/equal/worse, p) | mean change [95%] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| descent | 24/24 [86–100%] | 6.252 | 11.9% | 5 | 4.29 | 145 | 226 | — | — | — | — |
| uphill | 24/24 [86–100%] | 6.168 | 10.1% | 8 | 3.54 | 150 | 236 | 6/18/0, p=0.0312 | -1.5% [-3.3, -0.3] | — | — |
| opportunistic | 24/24 [86–100%] | 6.156 | 9.9% | 10 | 3.33 | 149 | 234 | 6/17/1, p=0.125 | -1.7% [-3.7, -0.1] | — | — |
| adaptive | 24/24 [86–100%] | 6.365 | 13.6% | 3 | 4.92 | 149 | 234 | 8/2/14, p=0.2863 | +1.6% [-1.6, +4.7] | — | — |
| alns | 24/24 [86–100%] | 5.802 | 4.4% | 9 | 2.79 | 149 | 222 | 15/2/7, p=0.1338 | -5.6% [-10.4, -0.4] | — | — |
| alns_refined | 24/24 [86–100%] | 5.965 | 7.2% | 6 | 3.92 | 121 | 217 | 14/1/9, p=0.4049 | -3.3% [-7.5, +1.7] | 3/10/11, p=0.0574 | +2.8% [+1.2, +4.8] |
| alns_opportunistic | 24/24 [86–100%] | 5.802 | 4.4% | 9 | 2.79 | 149 | 222 | 15/2/7, p=0.1338 | -5.6% [-10.4, -0.4] | 0/24/0, p=1.0 | +0.0% [+0.0, +0.0] |
| alns_checkpoint | 24/24 [86–100%] | 5.884 | 5.8% | 7 | 3.21 | 132 | 228 | 15/1/8, p=0.21 | -4.5% [-8.9, +0.4] | 3/14/7, p=0.3438 | +1.4% [+0.4, +2.7] |

## L-homogeneous

| strategy | feasible (95% CI) | mean cost (M) | mean regret | found the best | rank | calls | time units | vs descent (better/equal/worse, p) | mean change [95%] | vs alns (better/equal/worse, p) | mean change [95%] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| descent | 6/6 [61–100%] | 6.298 | 15.1% | 2 | 3.67 | 150 | 256 | — | — | — | — |
| uphill | 6/6 [61–100%] | 6.298 | 15.1% | 2 | 3.67 | 150 | 256 | 0/6/0, p=1.0 | +0.0% [+0.0, +0.0] | — | — |
| opportunistic | 6/6 [61–100%] | 6.298 | 15.1% | 2 | 3.67 | 150 | 256 | 0/6/0, p=1.0 | +0.0% [+0.0, +0.0] | — | — |
| adaptive | 6/6 [61–100%] | 6.647 | 21.6% | 0 | 6.67 | 150 | 259 | 0/0/6, p=0.0312 | +5.6% [+3.1, +9.1] | — | — |
| alns | 6/6 [61–100%] | 5.539 | 2.5% | 4 | 2.33 | 149 | 236 | 4/0/2, p=0.6875 | -9.4% [-20.3, +1.8] | — | — |
| alns_refined | 6/6 [61–100%] | 5.889 | 8.8% | 1 | 4.33 | 125 | 254 | 4/0/2, p=0.6875 | -4.2% [-13.2, +6.0] | 0/2/4, p=0.125 | +6.3% [+1.3, +12.4] |
| alns_opportunistic | 6/6 [61–100%] | 5.539 | 2.5% | 4 | 2.33 | 149 | 236 | 4/0/2, p=0.6875 | -9.4% [-20.3, +1.8] | 0/6/0, p=1.0 | +0.0% [+0.0, +0.0] |
| alns_checkpoint | 6/6 [61–100%] | 5.707 | 5.4% | 2 | 3.00 | 136 | 265 | 4/0/2, p=0.6875 | -7.2% [-15.9, +2.4] | 0/4/2, p=0.5 | +2.9% [+0.0, +6.1] |

## L-two-layer

| strategy | feasible (95% CI) | mean cost (M) | mean regret | found the best | rank | calls | time units | vs descent (better/equal/worse, p) | mean change [95%] | vs alns (better/equal/worse, p) | mean change [95%] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| descent | 6/6 [61–100%] | 6.338 | 11.2% | 1 | 4.67 | 150 | 254 | — | — | — | — |
| uphill | 6/6 [61–100%] | 6.301 | 10.5% | 2 | 3.83 | 150 | 257 | 1/5/0, p=1.0 | -0.7% [-2.2, +0.0] | — | — |
| opportunistic | 6/6 [61–100%] | 6.301 | 10.5% | 2 | 3.83 | 150 | 257 | 1/5/0, p=1.0 | -0.7% [-2.2, +0.0] | — | — |
| adaptive | 6/6 [61–100%] | 6.683 | 16.6% | 1 | 5.33 | 150 | 259 | 2/0/4, p=0.6875 | +4.6% [-0.9, +11.6] | — | — |
| alns | 6/6 [61–100%] | 5.762 | 1.8% | 1 | 2.67 | 150 | 237 | 5/0/1, p=0.2188 | -7.5% [-15.7, -0.6] | — | — |
| alns_refined | 6/6 [61–100%] | 5.907 | 4.3% | 1 | 3.83 | 126 | 259 | 4/0/2, p=0.6875 | -5.4% [-12.5, +0.8] | 1/2/3, p=0.625 | +2.5% [+0.2, +5.1] |
| alns_opportunistic | 6/6 [61–100%] | 5.762 | 1.8% | 1 | 2.67 | 150 | 237 | 5/0/1, p=0.2188 | -7.5% [-15.7, -0.6] | 0/6/0, p=1.0 | +0.0% [+0.0, +0.0] |
| alns_checkpoint | 6/6 [61–100%] | 5.816 | 2.8% | 1 | 3.33 | 137 | 270 | 4/0/2, p=0.6875 | -6.7% [-14.1, +0.2] | 1/3/2, p=1.0 | +1.0% [-0.4, +2.6] |

## square-building

| strategy | feasible (95% CI) | mean cost (M) | mean regret | found the best | rank | calls | time units | vs descent (better/equal/worse, p) | mean change [95%] | vs alns (better/equal/worse, p) | mean change [95%] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| descent | 6/6 [61–100%] | 5.083 | 12.4% | 1 | 5.33 | 130 | 192 | — | — | — | — |
| uphill | 6/6 [61–100%] | 4.842 | 6.8% | 2 | 3.50 | 150 | 226 | 3/3/0, p=0.25 | -4.5% [-10.7, -0.5] | — | — |
| opportunistic | 6/6 [61–100%] | 4.802 | 6.0% | 4 | 2.50 | 149 | 223 | 4/2/0, p=0.125 | -5.3% [-11.1, -1.2] | — | — |
| adaptive | 6/6 [61–100%] | 4.947 | 9.3% | 1 | 3.67 | 149 | 218 | 4/1/1, p=0.375 | -2.1% [-9.3, +5.4] | — | — |
| alns | 6/6 [61–100%] | 4.871 | 7.7% | 3 | 2.50 | 149 | 209 | 4/1/1, p=0.375 | -3.1% [-14.5, +9.0] | — | — |
| alns_refined | 6/6 [61–100%] | 4.919 | 8.8% | 2 | 3.67 | 115 | 174 | 3/1/2, p=1.0 | -2.3% [-13.0, +9.2] | 0/4/2, p=0.5 | +1.1% [+0.0, +3.0] |
| alns_opportunistic | 6/6 [61–100%] | 4.871 | 7.7% | 3 | 2.50 | 149 | 209 | 4/1/1, p=0.375 | -3.1% [-14.5, +9.0] | 0/6/0, p=1.0 | +0.0% [+0.0, +0.0] |
| alns_checkpoint | 6/6 [61–100%] | 4.910 | 8.6% | 2 | 2.83 | 127 | 188 | 4/1/1, p=0.375 | -2.4% [-13.0, +9.1] | 0/5/1, p=1.0 | +0.9% [+0.0, +2.8] |

## trapezoid

| strategy | feasible (95% CI) | mean cost (M) | mean regret | found the best | rank | calls | time units | vs descent (better/equal/worse, p) | mean change [95%] | vs alns (better/equal/worse, p) | mean change [95%] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| descent | 6/6 [61–100%] | 7.286 | 9.0% | 1 | 3.50 | 148 | 201 | — | — | — | — |
| uphill | 6/6 [61–100%] | 7.230 | 8.1% | 2 | 3.17 | 149 | 205 | 2/4/0, p=0.5 | -0.8% [-1.8, +0.0] | — | — |
| opportunistic | 6/6 [61–100%] | 7.222 | 8.0% | 2 | 3.33 | 148 | 199 | 1/4/1, p=1.0 | -0.8% [-5.0, +2.7] | — | — |
| adaptive | 6/6 [61–100%] | 7.182 | 7.1% | 1 | 4.00 | 148 | 201 | 2/1/3, p=1.0 | -1.6% [-6.2, +2.6] | — | — |
| alns | 6/6 [61–100%] | 7.037 | 5.5% | 1 | 3.67 | 148 | 204 | 2/1/3, p=1.0 | -2.5% [-11.3, +5.6] | — | — |
| alns_refined | 6/6 [61–100%] | 7.146 | 6.9% | 2 | 3.83 | 117 | 179 | 3/0/3, p=1.0 | -1.4% [-9.0, +5.8] | 2/2/2, p=1.0 | +1.4% [-0.2, +3.8] |
| alns_opportunistic | 6/6 [61–100%] | 7.037 | 5.5% | 1 | 3.67 | 148 | 204 | 2/1/3, p=1.0 | -2.5% [-11.3, +5.6] | 0/6/0, p=1.0 | +0.0% [+0.0, +0.0] |
| alns_checkpoint | 6/6 [61–100%] | 7.105 | 6.3% | 2 | 3.67 | 129 | 191 | 3/0/3, p=1.0 | -1.8% [-9.8, +5.8] | 2/2/2, p=1.0 | +0.8% [-0.2, +2.2] |

## What each kind of move earned

```json
{
 "adaptive": {
  "lns": {
   "used": 0,
   "incumbent": 0,
   "improving": 0,
   "novel": 0
  },
  "atomic": {
   "used": 46206,
   "incumbent": 212,
   "improving": 6462,
   "novel": 16507
  },
  "planning_failures": 0
 },
 "alns": {
  "lns": {
   "used": 8616,
   "incumbent": 80,
   "improving": 907,
   "novel": 1797
  },
  "atomic": {
   "used": 23064,
   "incumbent": 97,
   "improving": 3209,
   "novel": 8545
  },
  "planning_failures": 4253
 },
 "alns_refined": {
  "lns": {
   "used": 7922,
   "incumbent": 67,
   "improving": 964,
   "novel": 1362
  },
  "atomic": {
   "used": 21233,
   "incumbent": 82,
   "improving": 3018,
   "novel": 8047
  },
  "planning_failures": 4308
 },
 "alns_opportunistic": {
  "lns": {
   "used": 8616,
   "incumbent": 80,
   "improving": 907,
   "novel": 1797
  },
  "atomic": {
   "used": 23064,
   "incumbent": 97,
   "improving": 3209,
   "novel": 8545
  },
  "planning_failures": 4253
 },
 "alns_checkpoint": {
  "lns": {
   "used": 8361,
   "incumbent": 72,
   "improving": 963,
   "novel": 1555
  },
  "atomic": {
   "used": 22097,
   "incumbent": 88,
   "improving": 2840,
   "novel": 8210
  },
  "planning_failures": 4310
 }
}
```
