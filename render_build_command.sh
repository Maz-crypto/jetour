#!/bin/bash
# render_build_command.sh

# تثبيت تبعيات النظام المطلوبة لبناء psycopg2
apt-get update && apt-get install -y libpq-dev gcc python3-dev

# تثبيت المتطلبات
pip install -r requirements.txt
