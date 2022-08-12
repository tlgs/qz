# Maintainer: Tiago Seabra <tlgs@user.noreply.github.com>

pkgname=qz-git
pkgver=r3.4f6481f
pkgrel=1
pkgdesc="Minimal time tracking CLI application."
arch=('x86_64')
url="https://github.com/tlgs/qz"
license=('UNLICENSE')
depends=('python')
makedepends=('git' 'python-build' 'python-installer')
source=('git+https://github.com/tlgs/qz')
md5sums=('SKIP')

pkgver() {
  cd "$srcdir/${pkgname%-git}" || exit
  ( set -o pipefail
    git describe --long 2>/dev/null | sed 's/\([^-]*-g\)/r\1/;s/-/./g' ||
    printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
  )
}

build() {
  cd "$srcdir/${pkgname%-git}" || exit
  python -m build --wheel
}

package() {
  cd "$srcdir/${pkgname%-git}" || exit
  python -m installer --destdir="$pkgdir" dist/*.whl
}
