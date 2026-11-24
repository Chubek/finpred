/* Exercise the real host socket boundary without opening a connection. */
#include "../plugins/dragnet/native/kernels.c"
#include <assert.h>

int main(void) {
  const char *denied[] = {"0.0.0.0","10.0.0.1","127.0.0.1","169.254.169.254",
    "172.16.0.1","172.31.255.254","192.168.0.1","100.64.0.1","198.18.0.1",
    "192.0.0.1","192.0.2.1","198.51.100.1","203.0.113.1","224.0.0.1",
    "255.255.255.255"};
  struct curl_sockaddr addr;
  memset(&addr,0,sizeof addr);
  addr.family = AF_INET;
  addr.socktype = SOCK_STREAM;
  addr.protocol = IPPROTO_TCP;
  struct sockaddr_in *in = (struct sockaddr_in *)&addr.addr;
  in->sin_family = AF_INET;
  for (size_t i = 0; i < sizeof denied/sizeof denied[0]; i++) {
    assert(inet_pton(AF_INET,denied[i],&in->sin_addr) == 1);
    assert(open_socket(NULL,CURLSOCKTYPE_IPCXN,&addr) == CURL_SOCKET_BAD);
  }
  addr.family = AF_INET6;
  assert(open_socket(NULL,CURLSOCKTYPE_IPCXN,&addr) == CURL_SOCKET_BAD);
  addr.family = AF_INET;
  assert(inet_pton(AF_INET,"8.8.8.8",&in->sin_addr) == 1);
  curl_socket_t socket = open_socket(NULL,CURLSOCKTYPE_IPCXN,&addr);
  assert(socket != CURL_SOCKET_BAD);
  close(socket); /* Created only; never connected. */
  cancelled = 1;
  assert(open_socket(NULL,CURLSOCKTYPE_IPCXN,&addr) == CURL_SOCKET_BAD);
  puts("dragnet_socket_policy_ok=true denied=17 cancellation=passed");
  return 0;
}
