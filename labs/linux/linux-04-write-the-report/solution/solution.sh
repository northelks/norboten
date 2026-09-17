#!/bin/sh
set -eu
cat > /usr/local/bin/top-talkers <<'SCRIPT'
#!/bin/bash
# top-talkers [-n N] FILE — the N busiest client addresses in an access log.
set -uo pipefail
n=5
while getopts ":n:" opt; do
    case $opt in
        n) n=$OPTARG ;;
        :) echo "top-talkers: invalid count" >&2; exit 2 ;;
        *) echo "top-talkers: unknown option -$OPTARG" >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[[ $n =~ ^[1-9][0-9]*$ ]] || { echo "top-talkers: invalid count" >&2; exit 2; }
file=${1:-}
[[ -n $file && -r $file && -f $file ]] || { echo "top-talkers: cannot read $file" >&2; exit 1; }

grep -v -e '^#' -e '^[[:space:]]*$' -- "$file" \
    | awk '{print $1}' \
    | LC_ALL=C sort | uniq -c \
    | awk '{print $1, $2}' \
    | LC_ALL=C sort -k1,1nr -k2,2 \
    | head -n "$n"
exit 0
SCRIPT
chmod 755 /usr/local/bin/top-talkers
