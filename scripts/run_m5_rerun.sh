#!/bin/bash
# M5 rerun: the observer parser now accepts several observers per channel.
# The prompt is identical to the original A run, so A vs A3 isolates the parser.
# A3 = the nine fixtures with the shipped (Qwen contract + Qwen guard) system.
# H2 = mace on the first held-out batch (baselines from /root/m5/H stay valid).
# H3 = all four modes on the second held-out batch.
set -u
cd /root/mace
export OLLAMA_MODELS=/root/autodl-tmp/ollama_models
PY=/root/miniconda3/bin/python

run_one () {  # fixture mode outdir
  echo "==== $(basename "$3") $2 $(date +%H:%M:%S)"
  "$PY" -m mace.cli run --fixture "$1.json" --provider ollama \
      --model qwen2.5-coder:32b --mode "$2" --rounds 3 --seed 42 --out "$3"
}

rm -rf /root/m5/A3 /root/m5/H2 /root/m5/H3
mkdir -p /root/m5/A3 /root/m5/H2 /root/m5/H3

for f in alt_masking dead_flag dedup_channel dict_slot modulo_absorb \
         overwrite_channel parity_snap sort_channel swap_channels; do
  run_one "$f" mace /root/m5/A3/"$f"
done

for f in dead_flag dict_slot parity_snap; do
  run_one "$f" mace /root/m5/H2/"$f"
done

for f in clamp_absorb toggle_pair; do
  for m in direct generic fixed mace; do
    run_one "$f" "$m" /root/m5/H3/"$f"
  done
done

echo "==== M5 RERUN DONE $(date +%H:%M:%S)"
