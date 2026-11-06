#!/bin/bash
# Three-round baselines on the nine development fixtures, same model/seed and
# the same bounded checker.  Token-matched direct (12 rounds) lives in m5/T.
set -u
cd /root/mace
export OLLAMA_MODELS=/root/autodl-tmp/ollama_models
PY=/root/miniconda3/bin/python
rm -rf /root/m5/base
mkdir -p /root/m5/base
for f in alt_masking dead_flag dedup_channel dict_slot modulo_absorb \
         overwrite_channel parity_snap sort_channel swap_channels; do
  for m in direct generic fixed; do
    echo "==== base $f $m $(date +%H:%M:%S)"
    "$PY" -m mace.cli run --fixture "$f.json" --provider ollama \
        --model qwen2.5-coder:32b --mode "$m" --rounds 3 --seed 42 \
        --out /root/m5/base/"$f"
  done
done
echo "==== BASE DONE $(date +%H:%M:%S)"
