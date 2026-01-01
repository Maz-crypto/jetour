# render_build_command.sh
# تأكد من تثبيت التبعيات النظامية
apt-get update && apt-get install -y libpq-dev gcc
pip install -r requirements.txt
