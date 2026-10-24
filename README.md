# csvcut -- cut(1) for CSVs

Just what it says on the tin.  Simple version of `cut(1)` that works on CSVs.

BSD/GNU cut(1) honor input order on `-f`, even if -f is specified in another
order.  Since reordering fields is a natural operation on CSVs, the
--selection-order flag gives you that.

## Sample Usage

```shell
$ echo "1,2,3" > test.csv
$ csvcut -f1 < test.csv
1
$ csvcut -f1-2 < test.csv
1,2
$ csvcut -f1,3 < test.csv
1,3
$ csvcut -f-3 , < test.csv
1,2,3
$ csvcut -f1-2 , < test.csv
1,2
$ csvcut -f3,2,1 < test.csv
1,2,3
$ csvcut --selection-order -f3,2,1 < test.csv
3,2,1
```

## License Caveat

This script is the work of a large language model, and depending on as-yet
unsettled development of copyright law, may prove ineligible for copyright.
To the extent such works _are_ eligible for copyright, this code is released
under terms of the GNU General Public License v2.

