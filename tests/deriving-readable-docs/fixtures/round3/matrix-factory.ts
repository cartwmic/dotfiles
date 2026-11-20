export function createMatrixPort(options: MatrixPortOptions): MatrixPort {
  const roomId = options.roomId;
  if (!ROOM_ID.test(roomId)) throw new Error('room_id ' + JSON.stringify(roomId) + ' is not a Matrix room id (!id or !id:server)');
  const { spaceId } = options;
  if (spaceId !== undefined && !ROOM_ID.test(spaceId)) throw new Error('space_id ' + JSON.stringify(spaceId) + ' is not a Matrix room id');
  const MAIN: Place = { room: roomId, head: null, threadRoot: null };
  const port: MatrixPort = {
    source: 'matrix',
    async startThread(_channelId, messageId, name) {
      eventIdOf(messageId);
      if (spaceId === undefined) return { id: messageId };
      await joinSpaces();
    },
    async history() { throw new ChatRejection(501, 'Matrix history is unsupported'); },
  };
  return port;
}
