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
MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" -e "SET GLOBAL max_allowed_packet=536870912; CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
for file in dumps/*.sql; do
  if [[ -f "$file" ]]; then
    MYSQL_PWD="$DB_PASS" mysql --max-allowed-packet=512M -u"$DB_USER" "$DB_NAME" < "$file"
  fi;
done

# The dump mixes utf8mb4_0900_ai_ci tables with utf8mb4_general_ci columns, and
# upgrade processes that join them fail with "Illegal mix of collations"
echo ">>> Unifying table collations..."
MYSQL_PWD="$DB_PASS" mysql -N -u"$DB_USER" -e "SELECT CONCAT('ALTER TABLE \`', table_name, '\` CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;') FROM information_schema.tables WHERE table_schema = '$DB_NAME' AND table_type = 'BASE TABLE' AND table_collation = 'utf8mb4_0900_ai_ci';" | MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" "$DB_NAME"

echo ">>> Checking out master branch..."
cd ../liferay-portal
git clean -fd
git checkout -- .
git fetch https://github.com/liferay/liferay-portal.git master
git checkout -f FETCH_HEAD

echo ">>> Building liferay-portal..."
ANT_OPTS=-Xmx8192m ant setup-profile-dxp
ANT_OPTS=-Xmx8192m ant all

# Dialect left the default build in LPD-95803, but liferay.com still uses it
echo ">>> Deploying the Dialect theme..."
(cd modules/apps/frontend-theme/frontend-theme-dialect && ../../../../gradlew deploy)

echo ">>> Copying bundles and configuring properties..."
cd ../liferay.com
find bundles -type f -exec bash -c 'dest="../bundles/${1#bundles/}" && mkdir -p "$(dirname "$dest")" && mv -f "$1" "$dest"' _ {} \;
rm -rf bundles
find "../bundles" -maxdepth 1 -type d -name "tomcat*" -exec cp -R tomcat/* {} \; 
sed -i'' -e "s|liferay.home=.*|liferay.home=$(cd ../bundles && pwd -P)|g" "../bundles/portal-setup-wizard.properties"
sed -i'' -e "s|jdbc.default.username=.*|jdbc.default.username=$DB_USER|g" "../bundles/portal-setup-wizard.properties"
sed -i'' -e "s|jdbc.default.password=.*|jdbc.default.password=$DB_PASS|g" "../bundles/portal-setup-wizard.properties"

# liferay.com templates use staticUtil, serviceLocator, and objectUtil, which
# FreeMarker restricts by default
mkdir -p ../bundles/osgi/configs
cat > ../bundles/osgi/configs/com.liferay.portal.template.freemarker.configuration.FreeMarkerEngineConfiguration.config <<'EOF'
restrictedVariables=[ \
  "httpUtil", \
  "httpUtilUnsafe", \
  "portletConfig", \
  "propsUtil", \
  "saxReaderUtil", \
  "staticFieldGetter", \
  ]
EOF

echo ">>> Running upgrade process..."
cd ../bundles
BUNDLES_DIR=$(pwd -P)
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

# Some fragment URL configuration values were serialized by reflection, nesting
# the real value in _jsonObject and map keys. Since LPD-97996 an unreadable URL
# renders as null instead of "#", which breaks fragments like the logo.
echo ">>> Repairing fragment URL configuration values..."
MYSQL_PWD="$DB_PASS" mysql -N --raw -u"$DB_USER" "$DB_NAME" -e "SELECT ctCollectionId, fragmentEntryLinkId, REPLACE(REPLACE(editableValues, '\n', ' '), '\t', ' ') FROM FragmentEntryLink WHERE editableValues LIKE '%\"_jsonObject\"%';" > fragment-entry-links.tsv
node - fragment-entry-links.tsv fragment-entry-links.sql <<'EOF'
const fs = require('fs');

function unwrap(value) {
  if (Array.isArray(value)) {
    return value.map(unwrap);
  }

  if (value === null || typeof value !== 'object') {
    return value;
  }

  if ('_jsonObject' in value) {
    const base = unwrap(value._jsonObject);
    const rest = {};

    for (const [key, entry] of Object.entries(value)) {
      if (key !== '_jsonObject') {
        rest[key] = unwrap(entry);
      }
    }

    if (base !== null && typeof base === 'object' && !Array.isArray(base)) {
      return Object.assign(base, rest);
    }

    return Object.keys(rest).length ? rest : base;
  }

  const keys = Object.keys(value);

  if (keys.includes('map') && keys.every((key) => key === 'map' || key === 'empty')) {
    return unwrap(value.map);
  }

  const result = {};

  for (const [key, entry] of Object.entries(value)) {
    result[key] = unwrap(entry);
  }

  return result;
}

const lines = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean);

const statements = lines.map((line) => {
  const [ctCollectionId, fragmentEntryLinkId, ...rest] = line.split('\t');
  const editableValues = JSON.stringify(unwrap(JSON.parse(rest.join('\t'))));

  return `UPDATE FragmentEntryLink SET editableValues = '${editableValues.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}' WHERE ctCollectionId = ${ctCollectionId} AND fragmentEntryLinkId = ${fragmentEntryLinkId};`;
});

fs.writeFileSync(process.argv[3], statements.join('\n') + '\n');

console.log(`>>> Repaired ${statements.length} fragment entry links`);
EOF
MYSQL_PWD="$DB_PASS" mysql -u"$DB_USER" "$DB_NAME" < fragment-entry-links.sql
rm -f fragment-entry-links.tsv fragment-entry-links.sql

echo ">>> Starting Tomcat..."
${BUNDLES_DIR}/${TOMCAT_DIR}/bin/catalina.sh jpda run
