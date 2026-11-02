/* A tiny program that runs Python under its own name ("frame-video-player").
 * SteamVR groups every python3 OpenVR client as one app; a distinct executable keeps
 * this player separate from other python3 panels (e.g. frame-steamvr-remote). */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
int main(int argc, char **argv) { return Py_BytesMain(argc, argv); }
