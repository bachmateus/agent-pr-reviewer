# Golden set do review

Casos com bug conhecido (e um limpo, que mede ruído). Rode depois de mexer no
prompt, no modelo ou no filtro:

```bash
python -m agent_scan eval              # 1ª vez chama o LLM; depois responde do cache
python -m agent_scan eval --no-cache   # força chamar o LLM de novo
```

Novo caso = nova pasta com `before.<ext>` (opcional), `after.<ext>` e
`expected.json`. Ver `src/agent_scan/evaluation.py`.
