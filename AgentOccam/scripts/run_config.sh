export SHOPPING="http://<webarena_server_address>:7770"
export SHOPPING_ADMIN="http://<webarena_server_address>:7780/admin"
export REDDIT="http://<webarena_server_address>:9999"
export GITLAB="http://<webarena_server_address>:8023"
export MAP="http://<webarena_server_address>:3000"
export WIKIPEDIA="http://<webarena_server_address>:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing"
export HOMEPAGE="http://<webarena_server_address>:4399"
export OPENAI_API_KEY=<openai_api_key>
conda activate webarena
python browser_env/auto_login.py
python eval_webarena.py --config AgentOccam/configs/AgentOccam.yml