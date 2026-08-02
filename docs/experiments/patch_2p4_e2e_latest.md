# Patch 2.4 GHz — post-fix results

- Project: `E:\cstprojects\patch_2p4_e2e.cst`
- Parameters: **13** → `['fmax_GHz', 'fmin_GHz', 'metal_t', 'inset', 'feed_w', 'gnd_y', 'gnd_x', 'patch_L', 'patch_W', 'sub_h', 'tan_d', 'eps_r', 'freq_GHz']`
- S11: **ok** metrics=`{'min_db': -7.8142342, 'freq_at_min_ghz': 2.34816}` n=86
- CST messages: `E:\cstprojects\patch_2p4_e2e\Result\output.txt`
- Views: `E:\cstprojects\exports\views_fixed` sizes=[('perspective', True, 3557), ('front', True, 3557), ('top', True, 3557), ('left', True, 3557), ('right', True, 3557)]

Geometry uses Parameter List expressions (`patch_W`, `patch_L`, …).
Edit parameters in CST then Rebuild / `cst_param_sweep_solve`.