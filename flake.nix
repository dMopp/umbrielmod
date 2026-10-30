{
  description = "GTK4/libadwaita configuration editor for the Umbriel Wayland compositor";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      version = builtins.head (
        builtins.match ''.*__version__ = "([^"]+)".*'' (builtins.readFile ./umbrielmod/__init__.py)
      );
    in
    {
      packages = forAllSystems (pkgs: {
        umbrielmod = pkgs.python3Packages.buildPythonApplication {
          pname = "umbrielmod";
          inherit version;
          pyproject = true;
          src = self;

          build-system = [ pkgs.python3Packages.hatchling ];
          dependencies = with pkgs.python3Packages; [
            pygobject3
            tomlkit
          ];
          nativeBuildInputs = with pkgs; [
            wrapGAppsHook4
            gobject-introspection
          ];
          buildInputs = with pkgs; [
            gtk4
            libadwaita
            gdk-pixbuf
          ];
          nativeCheckInputs = [
            pkgs.python3Packages.pytestCheckHook
            pkgs.git
          ];

          # One wrapper with both the GApps and the Python environment;
          # git is needed for the shader catalogue and the docs update.
          dontWrapGApps = true;
          preFixup = ''
            makeWrapperArgs+=("''${gappsWrapperArgs[@]}" --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.git ]})
          '';

          postInstall = ''
            install -Dm644 data/io.github.umbrielmod.desktop -t $out/share/applications
            install -Dm644 data/io.github.umbrielmod.svg -t $out/share/icons/hicolor/scalable/apps
          '';

          meta = {
            description = "GTK4/libadwaita configuration editor for the Umbriel Wayland compositor";
            homepage = "https://github.com/dMopp/umbrielmod";
            license = pkgs.lib.licenses.mit;
            platforms = pkgs.lib.platforms.linux;
            mainProgram = "umbrielmod";
          };
        };
        default = self.packages.${pkgs.stdenv.hostPlatform.system}.umbrielmod;
      });

      overlays.default = final: _prev: {
        umbrielmod = self.packages.${final.stdenv.hostPlatform.system}.umbrielmod;
      };

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            (python3.withPackages (ps: [
              ps.pygobject3
              ps.tomlkit
              ps.pytest
            ]))
            gobject-introspection
            gtk4
            libadwaita
            gdk-pixbuf
            git
            shellcheck
          ];
          shellHook = ''
            export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
          '';
        };
      });
    };
}
