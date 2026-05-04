#!/bin/bash

# If piped via curl|bash, re-execute from a temp file so no command can consume the pipe
if [ ! -t 0 ] && [ -z "$_LIFERAY_REEXEC" ]; then
  _tmpscript=$(mktemp)
  cat > "$_tmpscript"
  _LIFERAY_REEXEC=1 exec bash "$_tmpscript"
fi

set -e

if [[ ! -d liferay-portal ]]; then
  echo ">>> liferay-portal folder not found. Please run this script from your repository parent directory."
  exit 1
fi

if [[ ! -f liferay.com.zip ]]; then
  echo ">>> liferay.com.zip not found in the current folder. Please download it from: https://drive.google.com/file/d/1xwlC-LKxpd0VtQPaJFH0sHGduRY6tivy/view?usp=drive_link"
  exit 1
fi

EXPECTED_SIZE=43538318461
ACTUAL_SIZE=$(wc -c < liferay.com.zip | tr -d ' ')
if [[ "$ACTUAL_SIZE" != "$EXPECTED_SIZE" ]]; then
  echo ">>> liferay.com.zip size mismatch (expected ${EXPECTED_SIZE} bytes, got ${ACTUAL_SIZE} bytes). The file is outdated or corrupted."
  read -p ">>> Press Enter to delete the file or Ctrl+C to abort..." </dev/tty
  rm -f liferay.com.zip
  echo ">>> The file has been deleted. Please download the latest version from: https://drive.google.com/file/d/1xwlC-LKxpd0VtQPaJFH0sHGduRY6tivy/view?usp=drive_link"
  exit 1
fi

echo ">>> I will set up liferay.com for you."
echo ">>> You will need 150GB of free space and around 1 hour."
echo ">>> This is the plan:"
echo ">>>   1. Kill Tomcat, drop the database, and delete bundles"
echo ">>>   2. Load liferay.com database"
echo ">>>   3. Checkout master branch and build it"
echo ">>>   4. Load liferay.com bundles into it"
echo ">>>   5. Run the database upgrade"
echo ">>>   6. Start Tomcat"
echo ">>> Now is the time to make backups if you need them."
read -p ">>> Press Enter to continue or Ctrl+C to abort..." </dev/tty
read -p ">>> Enter your mysql username: " DB_USER </dev/tty
read -sp ">>> Enter your mysql password: " DB_PASS </dev/tty
echo ""

echo ">>> You are no longer needed, I'll take it from here."
read -p ">>> Press Enter to start..." </dev/tty
echo ">>> Killing Tomcat..."
pgrep -f tomcat | xargs kill -9 2>/dev/null || true

echo ">>> Dropping database..."
DB_NAME=lportal
MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" -e "DROP DATABASE IF EXISTS \`$DB_NAME\`;"

echo ">>> Deleting bundles..."
rm -rf bundles
echo ">>> Deleting liferay.com..."
rm -rf liferay.com
echo ">>> Unzipping liferay.com.zip..."
unzip -q liferay.com.zip
cd liferay.com

echo ">>> Creating and loading database..."
MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" -e "SET GLOBAL max_allowed_packet=536870912; CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8 collate utf8_general_ci;"
for file in dumps/*.sql; do
  if [[ -f "$file" ]]; then
    MYSQL_PWD="$DB_PASS" mysql --max-allowed-packet=512M -u"$DB_USER" "$DB_NAME" < "$file"
  fi;
done

echo ">>> Checking out master branch..."
cd ../liferay-portal
git clean -fd
git checkout -- .
git fetch https://github.com/liferay/liferay-portal.git master
git checkout -f FETCH_HEAD

echo ">>> Building liferay-portal..."
ANT_OPTS=-Xmx8192m ant setup-profile-dxp
ANT_OPTS=-Xmx8192m ant all
echo ">>> Copying bundles and configuring properties..."
cd ../liferay.com
find bundles -type f -exec bash -c 'dest="../bundles/${1#bundles/}" && mkdir -p "$(dirname "$dest")" && mv -f "$1" "$dest"' _ {} \;
rm -rf bundles
find "../bundles" -maxdepth 1 -type d -name "tomcat*" -exec cp -R tomcat/* {} \; 
sed -i'' -e "s|liferay.home=.*|liferay.home=$(cd ../bundles && pwd)|g" "../bundles/portal-setup-wizard.properties"
sed -i'' -e "s|jdbc.default.username=.*|jdbc.default.username=$DB_USER|g" "../bundles/portal-setup-wizard.properties"
sed -i'' -e "s|jdbc.default.password=.*|jdbc.default.password=$DB_PASS|g" "../bundles/portal-setup-wizard.properties"

echo ">>> Running upgrade process..."
cd ../bundles
BUNDLES_DIR=$(pwd)
TOMCAT_DIR=$(find . -maxdepth 1 -type d -name "tomcat*" | head -1 | xargs basename)

cat > tools/portal-tools-db-upgrade-client/app-server.properties <<EOF
dir=${BUNDLES_DIR}/${TOMCAT_DIR}
extra.lib.dirs=bin
global.lib.dir=lib
portal.dir=webapps/ROOT
server.detector.server.id=tomcat
EOF

cat > tools/portal-tools-db-upgrade-client/portal-upgrade-ext.properties <<EOF
liferay.home=${BUNDLES_DIR}
jdbc.default.driverClassName=com.mysql.cj.jdbc.Driver
jdbc.default.url=jdbc:mysql://localhost/${DB_NAME}?characterEncoding=UTF-8&dontTrackOpenResources=true&holdResultsOpenOverStatementClose=true&serverTimezone=GMT&useFastDateParsing=false&useUnicode=true
jdbc.default.username=${DB_USER}
jdbc.default.password=${DB_PASS}
EOF

tools/portal-tools-db-upgrade-client/db_upgrade_client.sh -j "-Xmx8192m"

MYSQL_PWD="$DB_PASS" mysql --max-allowed-packet=512M -u"$DB_USER" "$DB_NAME" < ../liferay.com/dumps/2-UpdateObjectField.sql

MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" "$DB_NAME" -e "UPDATE AssetListEntrySegmentsEntryRel SET typeSettings = replace(typeSettings, '514411727,', '') WHERE typeSettings LIKE '%514411727%';"
MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" "$DB_NAME" -e "DELETE FROM AssetListEntrySegmentsEntryRel WHERE segmentsEntryId IN (SELECT segmentsEntryId FROM SegmentsEntry WHERE name LIKE '%Geocoded%');"
MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" "$DB_NAME" -e "DELETE FROM SegmentsEntry WHERE name LIKE '%Geocoded%';"

echo ">>> Starting Tomcat..."
${BUNDLES_DIR}/${TOMCAT_DIR}/bin/catalina.sh jpda run
