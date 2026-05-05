      subroutine links_travel_time(j)

c --  j: vehicle internal ID

      use muc_mod
      use vector_mod
c      use bcdtr_mod	  
      integer js,IUpNode,IDnNode,LinkNo,js1,js2

c --  For George CT-GTM

 	open(file='Part_I.dat',unit=91,status='unknown')

c ------------------------------------------


c       print *,'Alex-printing-linkstravel time',j

      do i=1,noofarcs
        linktraveltime(j,i)=s(i)/SpeedLimit(i)
      enddo

c --  Firt link on route:
      IUpNode=nodenum(iunod(isec(j)))
      IDnNode=nodenum(idnod(isec(j)))
      LinkNo=GetFLinkFromNode(idnum(IUpNode),idnum(IDnNode))
c	  print *,100,IUpNode,IDnNode,idnum(IUpNode),idnum(IDnNode)
c	  print *,
      linktraveltime(j,LinkNo)=VhcAtt_Value(j,1,4)

      if(vehclass2(j).ne.7.and.notin(j).eq.1)then 								! notin =1, the vehicle is out of the network	  
c	  print *,101	  
c -- vehicles that got out of the network (from second link and beyond):
        do js=2,VhcATT_Size(j)-1	
	  
      IUpNode=nodenum(nint(VhcAtt_Value(j,js-1,1)))
      IDnNode=nodenum(nint(VhcAtt_Value(j,js,1)))
	  
      LinkNo=GetFLinkFromNode(idnum(IUpNode),idnum(IDnNode))
      linktraveltime(j,LinkNo)=VhcAtt_Value(j,js,4)

      write(91,*)j,LinkNo,ttilnow(j)-linktraveltime(j,LinkNo),
     +linktraveltime(j,LinkNo)

        enddo
	  
      else
c	  print *,102	  
c -- vehicles still inside the network (from second link and beyond):
        do js=2,icurrnt(j)-1	
	  
      IUpNode=nodenum(nint(VhcAtt_Value(j,js-1,1)))
      IDnNode=nodenum(nint(VhcAtt_Value(j,js,1)))
	  
      LinkNo=GetFLinkFromNode(idnum(IUpNode),idnum(IDnNode))
      linktraveltime(j,LinkNo)=VhcAtt_Value(j,js,4)

      write(91,*)j,LinkNo,ttilnow(j)-linktraveltime(j,LinkNo),
     +linktraveltime(j,LinkNo)


        enddo
	
      endif


      close(91)

	  
      return
      end	  
