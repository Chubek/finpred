#include "on1x_runtime.h"
#include "probe_wire.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

const char *caravansary_market_probe_input(void)
{
    const size_t cap = CARAVANSARY_MARKET_PROBE_INPUT_LIMIT;
    char *data = malloc(cap + 1);
    if (!data) {
        on1x_tool_fail("cannot allocate market probe input");
        return "";
    }
    size_t length = 0;
    while (length <= cap) {
        ssize_t count = read(STDIN_FILENO, data + length, cap + 1 - length);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            if (count == 0 && length && !memchr(data, '\0', length)) {
                data[length] = '\0';
                const char *value = on1x_text_slice(data, 0, (int64_t)length);
                free(data);
                return value;
            }
            break;
        }
        length += (size_t)count;
    }
    free(data);
    on1x_tool_fail("invalid or oversized market probe input");
    return "";
}
