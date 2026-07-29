#!/usr/bin/env bash
#
# mcp-oauth.sh
#
# Configures a Liferay bundle so that its MCP server (/o/mcp) can be consumed by
# an MCP client over OAuth 2: RFC 9728 protected resource metadata, RFC 8414
# authorization server metadata and RFC 7591 dynamic client registration.
#
# One run does everything, and stops at the first thing that is not right:
#
#   1. writes the feature flags, the OSGi configurations and liferay.mode=test
#   2. waits for you to (re)start the server, since flags are read at startup
#   3. publishes the two .well-known metadata documents
#   4. verifies every endpoint an MCP client touches
#
# Running it again is harmless: every file is a marked block or is backed up,
# and the metadata is upserted by external reference code.
#
# --cleanup undoes all of it, deleting the published metadata first because that
# needs the feature flags still active. A restart completes it.
#
# Requirements: bash, curl and python3. No gradle or ant build is needed, and
# nothing else from this repository.
#
# Run it from inside a liferay-portal checkout. The bundle it configures is the
# one the checkout deploys to, read from app.server.properties: the bundle is
# app.server.parent.dir and the app server is app.server.<type>.dir, so nothing
# about their location or version is guessed.
#
# Usage:
#   ./mcp-oauth.sh [-u URL] [-U USER] [-P PASSWORD]
#   ./mcp-oauth.sh --cleanup
#
# Since it needs no other file, it can also be piped straight from GitHub, which
# is how the README documents it. Options go after "bash -s --", because bash is
# reading the script itself from stdin:
#   curl -sSL .../scripts/mcp-oauth.sh | bash
#   curl -sSL .../scripts/mcp-oauth.sh | bash -s -- --cleanup
#

set -euo pipefail

# Piped from curl, $0 is the interpreter and there is no file behind it, so fall
# back to the name this is published under rather than telling you to run "bash".
if [ -f "$0" ]; then
	SCRIPT_NAME=$(basename "$0")
else
	SCRIPT_NAME="mcp-oauth.sh"
fi

URL="http://localhost:8080"
ADMIN_USER="test@liferay.com"
ADMIN_PASSWORD="test"
CLEANUP=0

CONFIG_MCP="com.liferay.mcp.server.rest.internal.configuration.MCPServerConfiguration.config"
CONFIG_DCR="com.liferay.oauth2.provider.rest.internal.configuration.OAuth2DynamicRegistrationConfiguration.config"
CONFIG_CORS="com.liferay.portal.remote.cors.configuration.PortalCORSConfiguration~default.config"

# Feature flags: the MCP server, the .well-known metadata endpoints, dynamic
# client registration, and the OAuth Client metadata API used in step 3.
FEATURE_FLAGS=(LPD-63311 LPD-63415 LPD-63416 LPD-49855)

# Scopes advertised in the metadata and accepted from registering clients.
SCOPES="Liferay.OAuth.Client.REST.everything Liferay.MCP.Server.everything"

# Redirect URIs accepted from registering clients, as globs: any localhost port
# for CLI clients, the MCP Inspector callbacks, and the claude.ai callback.
REDIRECT_URIS=(
	"http://localhost:*/callback"
	"http://127.0.0.1:*/callback"
	"http://localhost:*/oauth/callback"
	"http://localhost:*/oauth/callback/debug"
	"https://claude.ai/api/mcp/auth_callback"
	"https://claude.com/api/mcp/auth_callback"
)

# Browser origins allowed to call /o/mcp and the metadata endpoints.
CORS_ORIGINS="http://localhost:6274 http://localhost:33418"

RESTART_TIMEOUT=900
STOP_TIMEOUT=300

# Fixed, never derived from the file name: renaming or symlinking this script
# must still find the block it wrote earlier instead of appending a second one.
MARKER_BEGIN="# BEGIN liferay-mcp-oauth"
MARKER_END="# END liferay-mcp-oauth"
DISABLED_PREFIX="#liferay-mcp-oauth-disabled# "
ERC_AS="L_MCP_OAUTH_AS"
ERC_PR="L_MCP_OAUTH_PR"

usage() {
	cat <<EOF
${SCRIPT_NAME} [OPTIONS]

Configure a Liferay bundle for MCP over OAuth 2, end to end.

Run it from inside a liferay-portal checkout: the bundle to configure is read
from its app.server.properties, so nothing about its location is guessed.

The server is yours to restart. This never starts or stops anything: it writes
what only startup reads, then waits for you to restart it.

Options:
  -u, --url URL            Portal URL, also used as the OAuth 2 issuer
                           (default: ${URL})
  -U, --user EMAIL         Portal administrator (default: ${ADMIN_USER})
  -P, --password PASSWORD  Administrator password (default: ${ADMIN_PASSWORD})
  -c, --cleanup            Undo everything instead: delete the published
                           metadata, the managed blocks and the OSGi configs
  -h, --help               Show this help

Scopes, redirect URIs and CORS origins are constants at the top of this script.
EOF
}

# --------------------------------------------------------------------------- io

if [ -t 1 ]; then
	C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
	C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
	C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

step() { printf '\n%s==> %s%s\n' "${C_BOLD}${C_BLUE}" "$*" "${C_RESET}"; }
info() { printf '    %s\n' "$*"; }
detail() { printf '    %s%s%s\n' "${C_DIM}" "$*" "${C_RESET}"; }
ok() { printf '    %s✓%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
warn() { printf '    %s!%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*"; }

die() {
	printf '\n    %s✗ %s%s\n' "${C_RED}${C_BOLD}" "$1" "${C_RESET}" >&2
	shift
	local line
	for line in "$@"; do
		printf '      %s%s%s\n' "${C_DIM}" "$line" "${C_RESET}" >&2
	done
	exit 1
}

# ---------------------------------------------------------------------- helpers

# Replaces (or appends) the managed block in a file, leaving the rest untouched.
write_managed_block() {
	python3 - "$1" "$MARKER_BEGIN" "$MARKER_END" "$2" <<'PYTHON'
import os, sys

path, begin, end, body = sys.argv[1:5]

block = begin + "\n" + body.rstrip("\n") + "\n" + end + "\n"

old = ""
if os.path.exists(path):
	with open(path, encoding="utf-8") as f:
		old = f.read()

if begin in old and end in old:
	head, rest = old.split(begin, 1)
	_, tail = rest.split(end, 1)
	new = head + block + tail.lstrip("\n")
else:
	new = old
	if new and not new.endswith("\n"):
		new += "\n"
	if new:
		new += "\n"
	new += block

if new == old:
	print("unchanged")
else:
	with open(path, "w", encoding="utf-8") as f:
		f.write(new)
	print("updated" if old else "created")
PYTHON
}

# Comments out occurrences of the managed feature flags that live outside the
# managed block, and reports any other feature flag duplicated in the file.
#
# Liferay combines repeated property keys instead of letting the last one win, so
# a key set both by hand and by this script resolves to "true,true", and
# GetterUtil.getBoolean() reads that as false. The flag then looks set in the
# file while the feature stays off, which is invisible until something 404s.
# Commenting out rather than deleting keeps the original line, and cleanup puts
# it back.
disable_duplicate_flags() {
	python3 - "$1" "$MARKER_BEGIN" "$MARKER_END" "$DISABLED_PREFIX" "${@:2}" <<'PYTHON'
import os, re, sys

path, begin, end, prefix = sys.argv[1:5]
keys = sys.argv[5:]

if not os.path.exists(path):
	print("0")
	sys.exit(0)

with open(path, encoding="utf-8") as f:
	lines = f.read().split("\n")

managed = re.compile(
	r"^[ \t]*(" + "|".join("feature\\.flag\\." + re.escape(key) for key in keys) + r")[ \t]*=")
any_flag = re.compile(r"^[ \t]*(feature\.flag\.[^.=\s]+)[ \t]*=")

inside = False
disabled = 0
counts = {}
out = []

for line in lines:
	if line.startswith(begin):
		inside = True
	elif line.startswith(end):
		inside = False
	elif not inside and not line.startswith(prefix):
		if managed.match(line):
			line = prefix + line
			disabled += 1
		else:
			match = any_flag.match(line)
			if match:
				counts[match.group(1)] = counts.get(match.group(1), 0) + 1

	out.append(line)

if disabled:
	with open(path, "w", encoding="utf-8") as f:
		f.write("\n".join(out))

others = sorted(key for key, count in counts.items() if count > 1)

print(disabled, " ".join(others))
PYTHON
}

# Puts back the lines disable_duplicate_flags commented out.
restore_disabled_flags() {
	python3 - "$1" "$DISABLED_PREFIX" <<'PYTHON'
import os, sys

path, prefix = sys.argv[1:3]

if not os.path.exists(path):
	print("0")
	sys.exit(0)

with open(path, encoding="utf-8") as f:
	lines = f.read().split("\n")

restored = 0
out = []

for line in lines:
	if line.startswith(prefix):
		line = line[len(prefix):]
		restored += 1
	out.append(line)

if restored:
	with open(path, "w", encoding="utf-8") as f:
		f.write("\n".join(out))

print(restored)
PYTHON
}

# Removes the managed block from a file, leaving the rest untouched.
remove_managed_block() {
	python3 - "$1" "$MARKER_BEGIN" "$MARKER_END" <<'PYTHON'
import os, sys

path, begin, end = sys.argv[1:4]

if not os.path.exists(path):
	print("absent")
	sys.exit(0)

with open(path, encoding="utf-8") as f:
	old = f.read()

if begin not in old or end not in old:
	print("absent")
	sys.exit(0)

head, rest = old.split(begin, 1)
_, tail = rest.split(end, 1)
new = head.rstrip("\n") + "\n" + tail.lstrip("\n")

# A file that held nothing but the block was created by this script.
if not new.strip():
	os.remove(path)
else:
	with open(path, "w", encoding="utf-8") as f:
		f.write(new)

print("removed")
PYTHON
}

# Undoes write_file: restores the newest backup it made, or deletes the file when
# it still holds exactly what this script wrote. Anything else is left alone, so
# cleaning up twice cannot delete a file that was restored by the first run.
remove_file() {
	local file=$1 label=$2 content=$3 backup

	if [ ! -f "$file" ]; then
		detail "${label}: absent"
		return
	fi

	backup=$(ls -1 "${file}".bak.* 2>/dev/null | sort | tail -1 || true)

	if [ -n "$backup" ]; then
		mv "$backup" "$file"
		ok "${label}: restored $(basename "$backup")"
	elif [ "$(cat "$file")" = "$content" ]; then
		rm "$file"
		ok "${label}: deleted"
	else
		warn "${label}: left alone, it does not hold what this script writes"
	fi
}

# Writes a file, backing up a different pre-existing version first.
write_file() {
	local file=$1 content=$2 label=$3

	if [ -f "$file" ] && [ "$(cat "$file")" = "$content" ]; then
		detail "${label}: unchanged"
	elif [ -f "$file" ]; then
		local backup="${file}.bak.$(date +%Y%m%d%H%M%S)"
		cp "$file" "$backup"
		printf '%s\n' "$content" > "$file"
		warn "${label}: replaced (previous version kept as $(basename "$backup"))"
	else
		printf '%s\n' "$content" > "$file"
		ok "${label}: created"
	fi
}

# Prints an OSGi .config array property, one quoted item per continued line.
osgi_list() {
	local key=$1
	shift

	printf '%s=[ \\\n' "$key"

	local item
	for item in "$@"; do
		printf '"%s", \\\n' "$item"
	done

	printf ']\n'
}

# Reads a property from the checkout's app server files. The per user file wins,
# which is the precedence the Liferay build itself uses.
app_server_property() {
	local file
	local -a files=()

	for file in "${REPO_DIR}/app.server.$(id -un).properties" \
		"${REPO_DIR}/app.server.properties"; do

		if [ -f "$file" ]; then
			files+=("$file")
		fi
	done

	[ "${#files[@]}" -gt 0 ] || return 0

	# awk rather than grep, because a missing match is not an error here and that
	# matters under set -e with pipefail, and the first file listed wins. The key
	# is matched with index() instead of a built regex, so the dots in it stay
	# literal on both BSD and GNU awk.
	awk -v key="$1" '
		{
			line = $0
			sub(/^[[:space:]]+/, "", line)
		}
		index(line, key "=") == 1 {
			value = substr(line, length(key) + 2)
			sub(/[[:space:]]+$/, "", value)
			print value
			exit
		}
	' "${files[@]}"
}

# Everything comes from the checkout this runs in, nothing is guessed: the bundle
# is wherever app.server.parent.dir points, and the app server directory is
# app.server.<type>.dir, so a Liferay Home holding several app server versions
# cannot be mistaken for the one the build deploys to.
is_checkout() {
	[ -f "${1}/app.server.properties" ] && [ -d "${1}/portal-impl" ]
}

# Nothing can be configured from outside a checkout, so say where to go instead
# of what is missing. A checkout just below is the likely mistake, since the
# parent directory is where the other scripts here are run from.
die_not_in_checkout() {
	local -a nearby=()
	local candidate

	for candidate in */; do
		if is_checkout "${candidate%/}"; then
			nearby+=("${candidate%/}")
		fi
	done

	if [ "${#nearby[@]}" -gt 0 ]; then
		local -a hints=()

		for candidate in "${nearby[@]}"; do
			hints+=("cd ${candidate}")
		done

		die "this has to run from inside a liferay-portal checkout, and ${PWD} is not one" \
			"there is one right here, so go in and run this again:" \
			"${hints[@]}"
	fi

	die "this has to run from inside a liferay-portal checkout, and ${PWD} is not one" \
		"cd to your liferay-portal checkout and run this again" \
		"the bundle to configure is read from that checkout's app.server.properties"
}

resolve_from_repo() {
	local dir=$PWD

	while :; do
		if is_checkout "$dir"; then
			REPO_DIR=$dir
			break
		fi

		[ "$dir" = "/" ] && die_not_in_checkout

		dir=$(dirname "$dir")
	done

	APP_SERVER_TYPE=$(app_server_property "app.server.type")

	[ -n "$APP_SERVER_TYPE" ] ||
		die "app.server.type is not set in ${REPO_DIR}/app.server.properties"

	local parent
	parent=$(app_server_property "app.server.parent.dir")

	[ -n "$parent" ] ||
		die "app.server.parent.dir is not set in ${REPO_DIR}/app.server.properties"

	parent=${parent//'${project.dir}'/$REPO_DIR}

	case "$parent" in
		/*) ;;
		*) parent="${REPO_DIR}/${parent}" ;;
	esac

	[ -d "$parent" ] || die "the bundle directory does not exist: ${parent}" \
		"app.server.parent.dir points there, deploy a bundle first"

	LIFERAY_HOME=$(cd "$parent" && pwd)

	local version server_dir version_token
	version=$(app_server_property "app.server.${APP_SERVER_TYPE}.version")
	server_dir=$(app_server_property "app.server.${APP_SERVER_TYPE}.dir")

	[ -n "$server_dir" ] ||
		die "app.server.${APP_SERVER_TYPE}.dir is not set in ${REPO_DIR}/app.server.properties"

	version_token='${app.server.'"${APP_SERVER_TYPE}"'.version}'
	server_dir=${server_dir//'${app.server.parent.dir}'/$LIFERAY_HOME}
	server_dir=${server_dir//"$version_token"/$version}

	case "$server_dir" in
		/*) ;;
		*) server_dir="${LIFERAY_HOME}/${server_dir}" ;;
	esac

	[ -d "$server_dir" ] || die "the app server directory does not exist: ${server_dir}" \
		"app.server.${APP_SERVER_TYPE}.dir points there, deploy a bundle first"

	APP_SERVER_DIR=$(cd "$server_dir" && pwd)
}

# Prints the system-ext.properties path inside the deployed portal.
# SystemProperties loads it from the classpath and pushes every entry through
# System.setProperty, which is how liferay.mode reaches PortalRunMode without
# touching any start script. It is not read from Liferay Home.
system_ext_file() {
	local classes="${APP_SERVER_DIR}/webapps/ROOT/WEB-INF/classes"

	[ -d "$classes" ] || return 1

	printf '%s\n' "${classes}/system-ext.properties"
}

# curl_json METHOD PATH [BODY] -> CURL_STATUS and CURL_BODY
curl_json() {
	local method=$1 path=$2 body=${3:-} response
	local -a args=(-s -m 60 -X "$method" -u "${ADMIN_USER}:${ADMIN_PASSWORD}"
		-H 'Accept: application/json' -w $'\n%{http_code}')

	[ -n "$body" ] && args+=(-H 'Content-Type: application/json' -d "$body")

	# Errors are reported from the status code, so curl stays quiet: this also
	# runs in the loop that polls a server which is still starting up.
	response=$(curl "${args[@]}" "${URL}${path}" 2>/dev/null || true)
	CURL_STATUS=${response##*$'\n'}
	CURL_BODY=${response%$'\n'*}
}

# curl_get URL -> CURL_STATUS and CURL_BODY, unauthenticated
curl_get() {
	local response
	response=$(curl -s -m 30 -H 'Accept: application/json' -w $'\n%{http_code}' "$1" 2>/dev/null || true)
	CURL_STATUS=${response##*$'\n'}
	CURL_BODY=${response%$'\n'*}
}

json_get() {
	python3 -c '
import json, sys
try:
	value = json.loads(sys.argv[1])
except Exception:
	sys.exit(0)
for key in sys.argv[2].split("."):
	if not isinstance(value, dict) or key not in value:
		sys.exit(0)
	value = value[key]
print(json.dumps(value) if isinstance(value, (list, dict)) else value)
' "$1" "$2" 2>/dev/null || true
}

# ------------------------------------------------------------------------- args

while [ $# -gt 0 ]; do
	case "$1" in
		-u|--url) URL=${2:?--url needs a value}; URL=${URL%/}; shift 2 ;;
		-U|--user) ADMIN_USER=${2:?--user needs a value}; shift 2 ;;
		-P|--password) ADMIN_PASSWORD=${2:?--password needs a value}; shift 2 ;;
		-c|--cleanup) CLEANUP=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown argument: $1" "run ${SCRIPT_NAME} --help" ;;
	esac
done

command -v curl >/dev/null 2>&1 || die "curl is required but was not found in PATH"
command -v python3 >/dev/null 2>&1 || die "python3 is required but was not found in PATH"


# The flags go straight into portal-ext.properties, which is created when it is
# not there. A tool that regenerates that file drops the block with it, in which
# case run this script again.
properties_file() { printf '%s\n' "${LIFERAY_HOME}/portal-ext.properties"; }

# -------------------------------------------------------------- config bodies

# Built once, because cleanup needs them too: a config file is only deleted when
# it still holds exactly this.
CONTENT_MCP='enabled=B"true"'

# Anonymous registration: no initial access token, no rate limit (0 is
# unlimited), and only the redirect URIs listed above.
CONTENT_DCR=$(
	osgi_list "oauth2.dynamic.registration.allowed.grant.types" "*"
	osgi_list "oauth2.dynamic.registration.allowed.hosts" "*"
	osgi_list "oauth2.dynamic.registration.allowed.redirect.uri.patterns" "${REDIRECT_URIS[@]}"
	osgi_list "oauth2.dynamic.registration.allowed.scopes" $SCOPES
	printf 'oauth2.dynamic.registration.maximum.number.of.registrations.per.hour=I"0"\n'
	printf 'oauth2.dynamic.registration.require.initial.access.token=B"false"\n'
)

# CORS, needed by MCP clients that run inside a browser.
CONTENT_CORS=$(
	printf 'configuration.name="Default\\ Portal\\ CORS\\ Configuration"\n'
	printf 'enabled=B"true"\n'
	osgi_list "filter.mapping.url.pattern" \
		"/.well-known/oauth-authorization-server" \
		"/.well-known/oauth-authorization-server/*" \
		"/.well-known/oauth-protected-resource" \
		"/.well-known/oauth-protected-resource/*" \
		"/o/mcp" \
		"/o/mcp/*" \
		"/o/oauth2/*"
	osgi_list "headers" \
		"Access-Control-Allow-Headers: Authorization, Content-Type, MCP-Protocol-Version" \
		"Access-Control-Allow-Methods: GET,POST,PUT,DELETE,OPTIONS,HEAD" \
		"Access-Control-Allow-Origin: ${URL} ${CORS_ORIGINS}"
)

# ------------------------------------------------------------------- cleanup

do_cleanup() {
	step "1/2 Published metadata"

	# Deleting needs the flags still active, so this runs before the files go.
	local erc status
	for erc in "as-local-metadata/by-external-reference-code/${ERC_AS}" \
		"pr-local-metadata/by-external-reference-code/${ERC_PR}"; do

		curl_json DELETE "/o/oauth-client/v1.0/oauth-client-${erc}"
		status=$CURL_STATUS

		case "$status" in
			200|204) ok "deleted ${erc##*/}" ;;
			404) detail "${erc##*/}: already absent" ;;
			000) warn "${URL} did not answer, leaving the metadata in place"
				detail "  start the server and re-run with --cleanup to remove it" ;;
			*) warn "${erc##*/}: HTTP ${status}, not deleted"
				detail "  the feature flags may already be off: ${CURL_BODY}" ;;
		esac
	done

	step "2/2 Configuration files"

	info "Checkout: ${REPO_DIR}"
	info "Bundle:   ${LIFERAY_HOME}"
	info "Deployed: $(basename "$APP_SERVER_DIR") (app.server.type=${APP_SERVER_TYPE})"

	case "$(remove_managed_block "$(properties_file)")" in
		removed) ok "portal-ext.properties: feature flag block removed" ;;
		*) detail "portal-ext.properties: no managed block" ;;
	esac

	local restored
	restored=$(restore_disabled_flags "$(properties_file)")

	if [ "$restored" != 0 ]; then
		ok "portal-ext.properties: restored ${restored} flag line(s) set before this ran"
	fi

	remove_file "${LIFERAY_HOME}/osgi/configs/${CONFIG_MCP}" \
		"MCPServerConfiguration.config" "$CONTENT_MCP"
	remove_file "${LIFERAY_HOME}/osgi/configs/${CONFIG_DCR}" \
		"OAuth2DynamicRegistrationConfiguration.config" "$CONTENT_DCR"
	remove_file "${LIFERAY_HOME}/osgi/configs/${CONFIG_CORS}" \
		"PortalCORSConfiguration~default.config" "$CONTENT_CORS"

	local system_ext_file
	if system_ext_file=$(system_ext_file); then
		case "$(remove_managed_block "$system_ext_file")" in
			removed) ok "system-ext.properties: liferay.mode=test removed" ;;
			*) detail "system-ext.properties: no managed block" ;;
		esac
	fi

	step "Cleaned up"
	info "You restart the server to drop the flags and the OSGi configs."
	info "Two things this cannot undo:"
	detail "  OAuth 2 clients that registered while this was enabled, in"
	detail "  Control Panel -> Security -> OAuth 2 Administration"
	detail "  data the MCP modules seeded on first boot, which is harmless"
}

# Records what was changed that only startup reads, so that step 2 can tell a
# server which merely answers from one that has actually picked the change up.
#
# The OSGi configs are deliberately not recorded: Felix watches osgi/configs and
# applies them to a running server, and /o/mcp answering 401 already proves the
# MCP one landed. The feature flags and liferay.mode=test have no such proof, and
# liferay.mode has no endpoint that reflects it at all: without this, a server
# holding the flags but started before liferay.mode=test reached the classpath
# passes both probes below and only fails in step 3, when Liferay rejects the
# http:// issuer, which is a bad place to learn a restart was needed.
RESTART_REASONS=""

needs_restart() {
	case "|${RESTART_REASONS}|" in
		*"|$1|"*) ;;
		*) RESTART_REASONS="${RESTART_REASONS}${RESTART_REASONS:+|}$1" ;;
	esac
}

# ------------------------------------------------- 1. files, read at startup

resolve_from_repo

if [ "$CLEANUP" = 1 ]; then
	do_cleanup
	exit 0
fi

step "1/4 Configuration files"

info "Checkout: ${REPO_DIR}"
info "Bundle:   ${LIFERAY_HOME}"
info "Deployed: $(basename "$APP_SERVER_DIR") (app.server.type=${APP_SERVER_TYPE})"

flags_body=""
for flag in "${FEATURE_FLAGS[@]}"; do
	flags_body+="feature.flag.${flag}=true"$'\n'
done

case "$(write_managed_block "$(properties_file)" "$flags_body")" in
	unchanged) detail "portal-ext.properties: feature flags already set" ;;
	*)
		ok "portal-ext.properties: $(printf '%s ' "${FEATURE_FLAGS[@]}")"
		needs_restart "the feature flags"
		;;
esac

# A flag set both here and by hand elsewhere in the file resolves to "true,true"
# and reads as false, so the feature stays off while the file looks right.
duplicates=$(disable_duplicate_flags "$(properties_file)" "${FEATURE_FLAGS[@]}")
disabled_count=$(printf '%s\n' "$duplicates" | awk '{print $1}')
other_duplicates=$(printf '%s\n' "$duplicates" | cut -s -d' ' -f2-)

if [ "$disabled_count" != 0 ]; then
	warn "portal-ext.properties: commented out ${disabled_count} duplicate flag line(s)"
	detail "  Liferay combines repeated keys, which would have read as false"
	needs_restart "the feature flags"
fi

if [ -n "$other_duplicates" ]; then
	warn "portal-ext.properties: these flags are set more than once and read as false"
	detail "  ${other_duplicates}"
fi

mkdir -p "${LIFERAY_HOME}/osgi/configs"

write_file "${LIFERAY_HOME}/osgi/configs/${CONFIG_MCP}" \
	"$CONTENT_MCP" \
	"MCPServerConfiguration.config"

write_file "${LIFERAY_HOME}/osgi/configs/${CONFIG_DCR}" \
	"$CONTENT_DCR" \
	"OAuth2DynamicRegistrationConfiguration.config"

write_file "${LIFERAY_HOME}/osgi/configs/${CONFIG_CORS}" \
	"$CONTENT_CORS" \
	"PortalCORSConfiguration~default.config"

# PortalRunMode.isTestMode() reads the liferay.mode system property. Without it
# Liferay refuses http:// endpoints in the OAuth 2 metadata and will not serve an
# http:// issuer, so it is only skipped for an https portal.
case "$URL" in
	https://*) detail "system-ext.properties: liferay.mode=test not needed for an https portal" ;;
	*)
		if system_ext_file=$(system_ext_file); then
			case "$(write_managed_block "$system_ext_file" 'liferay.mode=test')" in
				unchanged) detail "system-ext.properties: liferay.mode=test already present" ;;
				*)
					ok "system-ext.properties: liferay.mode=test"
					needs_restart "liferay.mode=test"
					;;
			esac
			detail "  ${system_ext_file#"${LIFERAY_HOME}/"}"
		else
			warn "portal webapp classes directory not found under ${LIFERAY_HOME}"
			warn "set liferay.mode=test yourself, on the classpath or as -Dliferay.mode=test"
		fi
		;;
esac

# ------------------------------------------------------ 2. wait for a restart

step "2/4 Server"

METADATA_API_STATUS=""
MCP_STATUS=""

# Two conditions, because the modules come up at their own pace: the OAuth Client
# metadata API answers only once the feature flags are active, and /o/mcp
# challenges with 401 only once the MCP module is registered. Waiting for just
# the first one races with the second.
server_ready() {
	curl_json GET "/o/oauth-client/v1.0/oauth-client-as-local-metadatas"
	METADATA_API_STATUS=$CURL_STATUS

	if [ "$CURL_STATUS" = 401 ] || [ "$CURL_STATUS" = 403 ]; then
		die "could not authenticate as ${ADMIN_USER} on ${URL}" "pass --user and --password"
	fi

	[ "$CURL_STATUS" = 200 ] || return 1

	MCP_STATUS=$(curl -s -o /dev/null -m 20 -w '%{http_code}' -X POST "${URL}/o/mcp" \
		-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
		-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' 2>/dev/null || true)

	[ "$MCP_STATUS" = 401 ]
}

# Anything answering at all, ready or not. A stale server answers long before it
# is ready, so this is what tells the two apart while waiting for a restart.
#
# No "|| echo 000" fallback: curl already prints 000 when it cannot connect, so
# echoing another one on its non-zero exit would make the status 000000, which is
# not 000, and a server that is down would read as answering.
server_answering() {
	local status
	status=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "${URL}/" 2>/dev/null || true)

	[ -n "$status" ] && [ "$status" != 000 ]
}

server_stopped() {
	! server_answering
}

# Polls $1 every $2 seconds, printing a dot per attempt, and gives up after $3,
# leaving what to make of that to the caller.
WAITED=0

wait_for() {
	local check=$1 interval=$2 timeout=$3 waited=0

	until "$check"; do
		if [ "$waited" -ge "$timeout" ]; then
			WAITED=$((WAITED + waited))
			printf '\n'
			return 1
		fi

		printf '.'
		sleep "$interval"
		waited=$((waited + interval))
	done

	WAITED=$((WAITED + waited))
}

if [ -z "$RESTART_REASONS" ] && server_ready; then
	ok "${URL} is up, with the feature flags active and /o/mcp answering"
else
	restart_reasons=${RESTART_REASONS//|/ and }
	restart_verb="start"

	# Said before anything else, and in the second person from here on, because a
	# script that waits reads a lot like a script that acts: people assume the
	# restart is being done for them and sit watching the dots. Nothing here ever
	# runs catalina.sh, by design, so that a server under a debugger or in the
	# foreground stays under the control of whoever started it.
	info "You restart the server, not this script — it only waits for you."

	# Being ready is not enough once something read at startup has changed: the
	# server answering now is the one that predates it. Wait for it to go away
	# first, so the restart is observed rather than assumed.
	#
	# Polled faster than the wait below because this is a window, not a state: it
	# opens when the port closes and shuts when the next boot binds it again.
	if [ -n "$RESTART_REASONS" ] && server_answering; then
		warn "a server is answering on ${URL} but it predates the files above"
		detail "  ${restart_reasons} — only read at startup"

		printf '\n    %swaiting for you to stop the server — up to %ss%s' \
			"${C_BOLD}" "$STOP_TIMEOUT" "${C_RESET}"

		if wait_for server_stopped 2 "$STOP_TIMEOUT"; then
			printf '\n'
			ok "server stopped"
		else
			# Never seen to stop, so the restart cannot be confirmed. Carrying on
			# is still better than failing here: if the server really is stale,
			# step 3 says so, and if it was restarted too quickly to catch, there
			# was never anything wrong.
			warn "the server never stopped, so its restart cannot be confirmed"
			detail "  carrying on: step 3 fails if it is still running without"
			detail "  ${restart_reasons}"
			restart_verb="restart"
		fi
	else
		info "The feature flags and liferay.mode=test are read at startup."
	fi

	# "start" rather than "restart" once the stop was seen, since at that point
	# there is nothing left to stop.
	printf '\n    %swaiting for you to %s the server — up to %ss%s' \
		"${C_BOLD}" "$restart_verb" "$RESTART_TIMEOUT" "${C_RESET}"

	wait_for server_ready 5 "$RESTART_TIMEOUT" ||
		die "${URL} did not become ready" \
			"OAuth Client metadata API: HTTP ${METADATA_API_STATUS}, expected 200" \
			"  needs these feature flags: $(printf '%s ' "${FEATURE_FLAGS[@]}")" \
			"POST /o/mcp: HTTP ${MCP_STATUS:-not reached}, expected 401" \
			"  needs LPD-63311 and MCPServerConfiguration enabled=true"

	printf '\n'
	ok "server is up and ready (${WAITED}s)"
fi

# ------------------------------------------------------- 3. publish metadata

step "3/4 OAuth 2 metadata"

# The scripted equivalent of Control Panel -> Security -> OAuth Client
# Administration -> Auth Server Local Metadata / Protected Resource Local
# Metadata. Upserted by external reference code, so re-runs just update.

# metadataJSON and oAuthASMetadataJSON are string fields holding JSON documents,
# hence the nested json.dumps.
as_body=$(python3 - "$ERC_AS" "$URL" "$SCOPES" <<'PYTHON'
import json, sys

erc, url, scopes = sys.argv[1:4]

print(json.dumps({
	"externalReferenceCode": erc,
	"issuer": url,
	"localWellKnownEnabled": True,
	"metadataJSON": json.dumps({
		"authorization_endpoint": url + "/o/oauth2/authorize",
		"grant_types_supported": ["authorization_code", "refresh_token"],
		"issuer": url,
		"jwks_uri": url + "/o/oauth2/jwks",
		"scopes_supported": scopes.split(),
		"subject_types_supported": ["public"],
		"token_endpoint": url + "/o/oauth2/token",
		"userinfo_endpoint": "",
	}),
	"oAuthASMetadataJSON": json.dumps({
		"registration_endpoint": url + "/o/oauth2/register",
	}),
}))
PYTHON
)

curl_json PUT "/o/oauth-client/v1.0/oauth-client-as-local-metadata/by-external-reference-code/${ERC_AS}" "$as_body"
[ "$CURL_STATUS" = 200 ] ||
	die "could not publish the authorization server metadata (HTTP ${CURL_STATUS})" "$CURL_BODY"
ok "authorization server metadata (RFC 8414)"

pr_body=$(python3 - "$ERC_PR" "$URL" "$SCOPES" <<'PYTHON'
import json, sys

erc, url, scopes = sys.argv[1:4]

print(json.dumps({
	"externalReferenceCode": erc,
	"localWellKnownEnabled": True,
	"metadataJSON": json.dumps({
		"authorization_servers": [url],
		"bearer_methods_supported": ["header"],
		"resource_name": "Liferay MCP Server",
		"scopes_supported": scopes.split(),
	}),
	"protectedResourceURI": url + "/o/mcp",
}))
PYTHON
)

curl_json PUT "/o/oauth-client/v1.0/oauth-client-pr-local-metadata/by-external-reference-code/${ERC_PR}" "$pr_body"
[ "$CURL_STATUS" = 200 ] ||
	die "could not publish the protected resource metadata (HTTP ${CURL_STATUS})" "$CURL_BODY"
ok "protected resource metadata (RFC 9728)"

# --------------------------------------------------------------- 4. verify

step "4/4 What an MCP client sees"

check_metadata() {
	local label=$1 url=$2 key=$3

	curl_get "$url"
	[ "$CURL_STATUS" = 200 ] || die "${label}: HTTP ${CURL_STATUS}" "$url"
	[ -n "$(json_get "$CURL_BODY" "$key")" ] ||
		die "${label}: 200 without a \"${key}\" entry" "$url" "$CURL_BODY"

	ok "${label}"
	detail "  ${url}"
}

check_metadata "authorization server metadata" \
	"${URL}/.well-known/oauth-authorization-server" "registration_endpoint"

check_metadata "protected resource metadata, built-in path" \
	"${URL}/o/.well-known/oauth-protected-resource/mcp" "resource"

check_metadata "protected resource metadata, RFC 9728 path" \
	"${URL}/.well-known/oauth-protected-resource/o/mcp" "resource"

# An unauthenticated call must answer 401 with the challenge that points the
# client at the protected resource metadata.
headers=$(curl -s -m 30 -D - -o /dev/null -X POST "${URL}/o/mcp" \
	-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
	-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
	-w '%{http_code}' || true)
status=${headers##*$'\n'}
challenge=$(printf '%s' "$headers" | grep -i '^www-authenticate:' | tr -d '\r' | cut -d' ' -f2- || true)

case "$status" in
	401)
		printf '%s' "$challenge" | grep -q 'resource_metadata=' ||
			die "POST /o/mcp answered 401 without a resource_metadata challenge" "$challenge"
		ok "unauthenticated POST /o/mcp challenges the client"
		detail "  ${challenge}"
		;;
	404)
		die "POST /o/mcp answered 404, the MCP server is off" \
			"expected feature.flag.LPD-63311=true and MCPServerConfiguration enabled=true" ;;
	*) die "POST /o/mcp answered HTTP ${status}, expected 401" ;;
esac

# Basic authentication goes through the same filter, so this proves the MCP
# server itself works, independently of the OAuth 2 plumbing.
mcp=$(curl -s -m 60 -X POST "${URL}/o/mcp" -u "${ADMIN_USER}:${ADMIN_PASSWORD}" \
	-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
	-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"mcp-oauth-setup","version":"1.0.0"}}}' \
	-w $'\n%{http_code}' || true)
printf '%s' "${mcp%$'\n'*}" | grep -q protocolVersion ||
	die "MCP initialize over basic authentication failed (HTTP ${mcp##*$'\n'})" "${mcp%$'\n'*}"
ok "MCP initialize over basic authentication"

# Dynamic client registration is the first thing an MCP client does, and the
# thing that breaks when the OSGi configuration above is not applied. The probe
# deliberately asks for a redirect URI no pattern can match, so registration is
# reached and rejected instead of leaving a client behind on every run: the
# rejection itself proves the endpoint is open and configured.
probe_uri="https://redirect-uri-probe.invalid/callback"

dcr=$(curl -s -m 30 -X POST "${URL}/o/oauth2/register" \
	-H 'Content-Type: application/json' -H 'Accept: application/json' \
	-d "$(python3 - "$probe_uri" <<'PYTHON'
import json, sys

print(json.dumps({
	"client_name": "mcp-oauth-setup probe",
	"grant_types": ["authorization_code"],
	"redirect_uris": [sys.argv[1]],
	"response_types": ["code"],
	"token_endpoint_auth_method": "none",
}))
PYTHON
)" \
	-w $'\n%{http_code}' || true)
dcr_status=${dcr##*$'\n'}
dcr_body=${dcr%$'\n'*}

case "$dcr_status" in
	400)
		[ "$(json_get "$dcr_body" error)" = "invalid_redirect_uri" ] ||
			die "dynamic client registration answered 400 unexpectedly" "$dcr_body"

		# Without the OSGi configuration there are no patterns at all, which is
		# rejected with the same error code but without naming the URI.
		case "$(json_get "$dcr_body" error_description)" in
			*"$probe_uri"*) ;;
			*) die "no redirect URI is accepted for open registration" \
				"oauth2.dynamic.registration.allowed.redirect.uri.patterns is empty" \
				"$dcr_body" ;;
		esac
		;;
	404) die "dynamic client registration is off (HTTP 404)" "feature.flag.LPD-63416 is not active" ;;
	401) die "dynamic client registration requires an initial access token (HTTP 401)" \
		"require.initial.access.token is still true: check the OSGi config filename and keys" \
		"${dcr_body:-<empty body>}" ;;
	500) die "dynamic client registration failed (HTTP 500)" \
		"the default service account user may be missing or inactive" "$dcr_body" ;;
	*) die "dynamic client registration answered HTTP ${dcr_status}, expected 400" "${dcr_body:-<empty body>}" ;;
esac

ok "dynamic client registration is open (RFC 7591)"
detail "  probed without registering a client"

# --------------------------------------------------------------------- summary

step "Ready"
cat <<EOF
    Connect Claude Code and authenticate, which opens the consent screen in
    your browser:

      claude mcp add --transport http liferay-oauth2 ${URL}/o/mcp && claude /mcp
EOF
