<?php
/**
 * Router script for `php -S` that stands in for the Apache .htaccess rewrites HAXcms PHP ships
 * with (root .htaccess: dot-file denial, /system/api/v1/* -> system/api/v1/index.php, and
 * "anything else that is not a file or directory -> index.php").
 *
 * Test harness only (tests/harness/haxcms_php_runtime.py); production HAXcms PHP runs under
 * Apache/nginx. SCRIPT_NAME is deliberately /index.php for API requests: the PHP route parser
 * (SiteRouteUtils::getRelativePathFromScript) strips dirname(SCRIPT_NAME) from the request path
 * and expects to see the full /system/api/... or /_sites/<site>/x/api/... path afterwards.
 */

$root = rtrim($_SERVER['DOCUMENT_ROOT'], '/');
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if (!is_string($path) || $path === '') {
    $path = '/';
}
$path = rawurldecode($path);

// never serve dot-files / dot-directories (root .htaccess: Security H-1), except .well-known
if (preg_match('#(^|/)\.(?!well-known(/|$))#', $path)) {
    http_response_code(403);
    exit;
}
// refuse path traversal outside the document root
$real = realpath($root . $path);
if ($real !== false && strpos($real, $root) !== 0) {
    http_response_code(403);
    exit;
}

$file = $root . $path;

// static files (anything that is not PHP) are served as-is by the built-in server
if ($path !== '/' && is_file($file) && !preg_match('#\.php$#', $path)) {
    return false;
}
// real PHP files run directly (install.php, index.php, ...), except the system API entry
// which wants the full request path
if (is_file($file) && preg_match('#\.php$#', $path)) {
    $_SERVER['SCRIPT_NAME'] = $path;
    chdir(dirname($file));
    require $file;
    return true;
}
// system API
if (strpos($path, '/system/api/v1/') === 0 || $path === '/system/api/v1') {
    $_SERVER['SCRIPT_NAME'] = '/index.php';
    $entry = $root . '/system/api/v1/index.php';
    chdir(dirname($entry));
    require $entry;
    return true;
}
// per-site routing (system/boilerplate/site/.htaccess: "not a file or directory -> ."): anything
// under /_sites/<name>/ runs that site's own index.php with SCRIPT_NAME set to it, so the
// route parser sees /x/api/v1/... relative to the site
if (preg_match('#^/(_sites|_published|_archived)/([^/]+)(/|$)#', $path, $m)
    && is_file($root . '/' . $m[1] . '/' . $m[2] . '/index.php')) {
    $siteIndex = $root . '/' . $m[1] . '/' . $m[2] . '/index.php';
    $_SERVER['SCRIPT_NAME'] = '/' . $m[1] . '/' . $m[2] . '/index.php';
    chdir(dirname($siteIndex));
    require $siteIndex;
    return true;
}
// everything else -> root index.php
$_SERVER['SCRIPT_NAME'] = '/index.php';
chdir($root);
require $root . '/index.php';
return true;
